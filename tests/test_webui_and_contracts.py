import os
import sys
import threading
import time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestCliAndActionsContracts:
    def test_main_exit_code_mapping_including_partial_success_2(self):
        import main

        assert main.resolve_exit_code(SimpleNamespace(status="success")) == 0
        assert main.resolve_exit_code(SimpleNamespace(status="skipped")) == 0
        assert main.resolve_exit_code(SimpleNamespace(status="partial_success")) == 2
        assert main.resolve_exit_code(SimpleNamespace(status="failed")) == 1
        assert main.resolve_exit_code(SimpleNamespace(status="cancelled")) == 130
        assert main.resolve_exit_code({"status": "partial_success"}) == 2
        assert main.resolve_exit_code(False) == 1
        assert main.resolve_exit_code(True) == 0

    def test_trigger_workflow_fixes_schedule_permissions_and_exit_code_gating(self):
        with open(".github/workflows/trigger.yml", "r", encoding="utf-8") as f:
            yml = f.read()

        assert "permissions:" in yml
        assert "contents: write" in yml
        assert "concurrency:" in yml
        # Must handle schedule trigger defaulting to hotspots instead of skipping all steps
        assert "github.event_name == 'schedule'" in yml or "github.event.inputs.task_type || 'hotspots'" in yml
        # Must preserve partial_success exit code 2 handling
        assert "exit_code" in yml
        assert "'2'" in yml or "== 2" in yml
        # Git commit/push step must ONLY run on exit_code 0 or 2 (NEVER unconditionally), and NEVER commit delivery journal/receipts
        commit_section = yml.split('name: "保存已成功发布的历史记录"', 1)[1]
        assert "steps.run_task.outputs.exit_code == '0' || steps.run_task.outputs.exit_code == '2'" in commit_section
        assert "git add data/delivery" not in commit_section
        assert "git add .autowechat_state" not in commit_section
        # Ephemeral runner MUST preserve account-bound encrypted journal/receipts even on uncertain/failure runs
        assert "actions/cache/restore@v4" in yml
        assert 'git push --force-with-lease="$STATE_REF:$PARENT"' in yml
        assert "steps.run_task.outputs.status != 'skipped'" in yml
        assert "account_hash" in yml
        assert "openssl" in yml and "-aes-256-cbc" in yml
        assert "hmac.compare_digest" in yml
        assert "umask 077" in yml
        assert "data/delivery.sqlite3" in yml
        assert "data/delivery_receipts" in yml

    def test_pytest_ini_sets_pythonpath(self):
        with open("pytest.ini", "r", encoding="utf-8") as f:
            content = f.read()
        assert "pythonpath = ." in content


class TestWebUIStatusSecurityAndOutcomes:
    def test_status_unauth_redacts_logs_and_does_not_drain_cursor_buffer(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", True)
        monkeypatch.setattr(webui, "WEBUI_TOKEN", "secret-token-123")
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        webui._append_webui_log("SENSITIVE | token=abc internal trace line 1\n")
        webui._append_webui_log("SENSITIVE | internal trace line 2\n")
        webui.ProcessState.set_last_run({
            "run_id": "run-1",
            "task_type": "hotspots",
            "status": "failed",
            "summary": "sensitive error detail",
            "error": "db crash",
        })

        # Unauthenticated health probe: 200, empty logs, no last_run leak, does not drain buffer
        unauth = client.get("/api/status?since=0")
        assert unauth.status_code == 200
        unauth_data = unauth.get_json()
        assert unauth_data["logs"] == []
        assert "last_run" not in unauth_data

        # Authenticated tab A and tab B both see logs via non-destructive cursor
        hdr = {"Authorization": "Bearer secret-token-123"}
        tab_a = client.get("/api/status?since=0", headers=hdr).get_json()
        tab_b = client.get("/api/status?since=0", headers=hdr).get_json()
        assert any("internal trace line 1" in line for line in tab_a["logs"])
        assert tab_a["logs"] == tab_b["logs"]
        assert tab_a["next_cursor"] == tab_b["next_cursor"]
        assert tab_a["last_run"]["status"] == "failed"

        # Subsequent poll from next_cursor gets 0 duplicate lines until new log arrives
        tab_a2 = client.get(f"/api/status?since={tab_a['next_cursor']}", headers=hdr).get_json()
        assert tab_a2["logs"] == []

    def test_run_workflow_thread_records_structured_outcome_statuses(self, monkeypatch):
        import webui
        from core.shared.runtime import WorkflowCancelled

        webui.ProcessState.set_running(False)
        webui.ProcessState.set_paused(False)

        with patch.object(
            webui,
            "run_main",
            return_value=SimpleNamespace(
                task_type="hotspots",
                status="partial_success",
                attempted=3,
                succeeded=2,
                failed=1,
                uncertain=0,
                skipped=0,
                summary="成功发布 2/3 篇",
                error="",
            ),
        ):
            webui.run_workflow_thread("hotspots")

        last = webui.ProcessState.get_last_run()
        assert last["status"] == "partial_success"
        assert last["succeeded"] == 2
        assert last["failed"] == 1

        with patch.object(webui, "run_main", side_effect=WorkflowCancelled("user stop")):
            webui.run_workflow_thread("hotspots")
        assert webui.ProcessState.get_last_run()["status"] == "cancelled"

    def test_consumes_runtime_log_buffer_read_since_and_workflow_outcome_to_dict(self, monkeypatch):
        import main
        import webui
        from core.shared.runtime import WorkflowOutcome, log_buffer, log_queue

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        _, cursor_before = log_buffer.read_since(0)
        log_queue.put_nowait("RUNTIME_CONTRACT | direct queue push\n")

        resp = client.get(f"/api/status?since={cursor_before}")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert any("direct queue push" in line for line in payload["logs"])
        assert payload["next_cursor"] > cursor_before

        outcome = WorkflowOutcome(
            task_type="hotspots",
            status="partial_success",
            attempted=3,
            succeeded=2,
            failed=1,
            uncertain=0,
            skipped=0,
            summary="2/3 成功",
            error="1 篇失败",
        )
        assert main.resolve_exit_code(outcome) == 2

        with patch.object(webui, "run_main", return_value=outcome):
            webui.run_workflow_thread("hotspots")

        last = client.get(f"/api/status?since={payload['next_cursor']}").get_json()["last_run"]
        expected = outcome.to_dict()
        for key in ("run_id", "task_type", "status", "attempted", "succeeded", "failed", "uncertain", "skipped", "summary", "error"):
            assert last[key] == expected[key]


class TestReviewAtomicContentionAndUncertainContracts:
    def _create_article(self, **kwargs):
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory

        session = db_manager.get_session()
        defaults = dict(
            title="Contract Test Article",
            source_type="hotspots",
            publish_date="2026-11-23",
            success_status=False,
            is_published=False,
            media_id=None,
            status="PENDING_REVIEW",
            quality_score=90.0,
        )
        defaults.update(kwargs)
        rec = ArticleHistory(**defaults)
        session.add(rec)
        session.commit()
        aid = rec.id
        db_manager.remove_session()
        return aid

    def _cleanup_article(self, aid):
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory

        session = db_manager.get_session()
        session.query(ArticleHistory).filter(ArticleHistory.id == aid).delete()
        session.commit()
        db_manager.remove_session()

    def _get_article(self, aid):
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory

        session = db_manager.get_session()
        rec = session.query(ArticleHistory).filter(ArticleHistory.id == aid).first()
        snap = (
            {
                "status": rec.status,
                "success_status": rec.success_status,
                "media_id": rec.media_id,
                "error_log": rec.error_log,
            }
            if rec
            else None
        )
        db_manager.remove_session()
        return snap

    @pytest.mark.parametrize("endpoint", ["approve", "reconcile"])
    def test_review_rejects_foreign_owner_and_unrelated_attempt(self, monkeypatch, tmp_path, endpoint):
        import webui
        from core.shared.delivery_journal import DeliveryJournal
        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        accessor = webui._LocalDeliveryAccessor("A", DeliveryJournal(tmp_path / "journal.db"))
        monkeypatch.setattr(webui, "_get_delivery_accessor", lambda: accessor)
        for owner, code in [("B", "ACCOUNT_MISMATCH"), ("A", "ATTEMPT_MISMATCH")]:
            aid = self._create_article(wechat_app_id=owner, status="DRAFT_PENDING_RECORD",
                                       media_id="receipt", delivery_attempt_id="original")
            try:
                response = webui.app.test_client().post("/api/review/" + endpoint,
                    json={"id": aid, "attempt_id": "other"})
                assert response.status_code == 409
                assert response.json["code"] == code
                assert self._get_article(aid)["status"] == "DRAFT_PENDING_RECORD"
            finally:
                self._cleanup_article(aid)

    @pytest.mark.parametrize("receipt", [False, True])
    def test_reconcile_abandoned_claim(self, monkeypatch, tmp_path, receipt):
        import webui
        from core.shared.delivery_journal import DeliveryJournal
        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        journal = DeliveryJournal(tmp_path / "journal.db")
        accessor = webui._LocalDeliveryAccessor("A", journal)
        monkeypatch.setattr(webui, "_get_delivery_accessor", lambda: accessor)
        monkeypatch.setattr(webui, "_get_publisher", lambda: pytest.fail("unexpected cloud request"))
        aid = self._create_article(wechat_app_id="A", status="APPROVING")
        try:
            body = {"id": aid}
            if receipt:
                row, _ = journal.claim("A", f"review_approve:{aid}", "title", {"article_id": aid})
                journal.resolve("A", row["attempt_id"], media_id="receipt")
                body = {"attempt_id": row["attempt_id"]}
            response = webui.app.test_client().post("/api/review/reconcile", json=body)
            assert response.status_code == 200
            assert self._get_article(aid)["status"] == ("DRAFT" if receipt else "PENDING_REVIEW")
            if receipt:
                assert journal.get("A", row["attempt_id"])["status"] == "DRAFT"
        finally:
            self._cleanup_article(aid)

    def test_cloud_uncertain_reconciles_by_attempt_marker_only_and_never_binds_by_title(self, monkeypatch, tmp_path):
        import webui
        from core.shared.delivery_journal import DeliveryJournal
        from core.shared.publisher import WeChatPublisher

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        aid = self._create_article(
            title="Real Marker Reconcile Article",
            status="PENDING_REVIEW",
        )
        preview_dir = os.path.join("data", "previews")
        os.makedirs(preview_dir, exist_ok=True)
        preview_file = os.path.join(preview_dir, f"{aid}.html")
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write("<p>real marker body</p>")

        journal = DeliveryJournal(tmp_path / "delivery.sqlite3")
        with patch.object(WeChatPublisher, "_ensure_valid_token", lambda self: setattr(self, "access_token", "tok")):
            pub = WeChatPublisher("wx_app_real_1", "wx_secret_real_1", journal=journal)

        captured_attempt_id = None
        cloud_items_state = {"items": []}

        def fake_post(url, *args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "draft/add" in url:
                raise TimeoutError("simulated read timeout after send")
            if "draft/batchget" in url:
                items = cloud_items_state["items"]
                resp.json.return_value = {"errcode": 0, "total_count": len(items), "item": items}
                return resp
            resp.json.return_value = {"errcode": 0}
            return resp

        pub.session = MagicMock()
        pub.session.post.side_effect = fake_post
        pub.upload_image = MagicMock(return_value="thumb_real_1")

        try:
            with patch.object(webui, "_get_publisher", return_value=pub):
                # 1. Approve hits timeout -> DeliveryJournal claims CLOUD_UNCERTAIN with stable operation_id & attempt_id
                resp_approve = client.post("/api/review/approve", json={"id": aid})
                assert resp_approve.status_code == 409
                app_data = resp_approve.get_json()
                assert app_data["code"] == "CLOUD_UNCERTAIN"
                assert app_data["review_status"] == "CLOUD_UNCERTAIN"
                captured_attempt_id = app_data["attempt_id"]
                assert captured_attempt_id
                assert self._get_article(aid)["status"] == "CLOUD_UNCERTAIN"

                # Verify stable operation_id and context stored in DeliveryJournal
                pending = pub.pending_deliveries()
                assert len(pending) == 1
                assert pending[0]["attempt_id"] == captured_attempt_id
                assert pending[0]["operation_id"] == f"review_approve:{aid}"
                assert pending[0]["context"]["article_id"] == aid

                # 2. Second approve MUST be blocked with 409 without resending
                resp_dup_uncertain = client.post("/api/review/approve", json={"id": aid})
                assert resp_dup_uncertain.status_code == 409
                assert resp_dup_uncertain.get_json()["code"] == "CLOUD_UNCERTAIN_REQUIRES_RECONCILE"

                # 3. Cloud has a draft with IDENTICAL TITLE but WITHOUT <!--autowechat:{attempt_id}-->
                #    Reconcile MUST NOT bind by title and MUST stay CLOUD_UNCERTAIN!
                cloud_items_state["items"] = [
                    {
                        "media_id": "wx_wrong_same_title_draft",
                        "content": {
                            "news_item": [
                                {"title": "Real Marker Reconcile Article", "content": "<p>different draft without marker</p>"}
                            ]
                        },
                    }
                ]
                resp_miss = client.post("/api/review/reconcile", json={"id": aid})
                assert resp_miss.status_code == 200
                miss_data = resp_miss.get_json()
                assert miss_data["found_in_cloud"] is False
                assert miss_data["unlocked"] is False
                assert miss_data["review_status"] == "CLOUD_UNCERTAIN"
                assert self._get_article(aid)["status"] == "CLOUD_UNCERTAIN"
                assert self._get_article(aid)["media_id"] is None

                # 4. Cloud draft body contains exact marker <!--autowechat:{attempt_id}-->
                #    Reconcile binds media_id, backfills locally, calls mark_delivery_recorded, converges to DRAFT!
                cloud_items_state["items"] = [
                    {
                        "media_id": "wx_verified_marker_media_99",
                        "content": {
                            "news_item": [
                                {
                                    "title": "Even Edited Title In WeChat",
                                    "content": f"<p>real marker body</p><!--autowechat:{captured_attempt_id}-->",
                                }
                            ]
                        },
                    }
                ]
                resp_hit = client.post("/api/review/reconcile", json={"id": aid})
                assert resp_hit.status_code == 200
                hit_data = resp_hit.get_json()
                assert hit_data["found_in_cloud"] is True
                assert hit_data["media_id"] == "wx_verified_marker_media_99"
                assert hit_data["review_status"] == "DRAFT"
                snap = self._get_article(aid)
                assert snap["status"] == "DRAFT"
                assert snap["media_id"] == "wx_verified_marker_media_99"
                assert snap["success_status"] is True
                assert pub.pending_deliveries() == []
                assert journal.get("wx_app_real_1", captured_attempt_id)["status"] == "DRAFT"

                # 5. Already-pushed DRAFT MUST reject /api/review/approve with 409
                resp_dup = client.post("/api/review/approve", json={"id": aid})
                assert resp_dup.status_code == 409
                assert resp_dup.get_json()["code"] == "ALREADY_PUSHED"
        finally:
            if os.path.exists(preview_file):
                os.remove(preview_file)
            if captured_attempt_id:
                att_p = os.path.join(preview_dir, f"attempt_{captured_attempt_id}.html")
                if os.path.exists(att_p):
                    os.remove(att_p)
            med_p = os.path.join(preview_dir, "wx_verified_marker_media_99.html")
            if os.path.exists(med_p):
                os.remove(med_p)
            self._cleanup_article(aid)

    def test_known_receipt_writeback_is_pure_local_and_never_calls_wechat_network(self, monkeypatch, tmp_path):
        import webui
        from core.shared.delivery_journal import DeliveryJournal

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        monkeypatch.setattr(webui, "_publisher_instance", None)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        journal = DeliveryJournal(tmp_path / "delivery.sqlite3")
        claim, owner = journal.claim("wx_local_app", "review_approve:local_test", "Local Receipt Test", {"source_type": "github"})
        assert owner is True
        attempt_id = claim["attempt_id"]
        journal.resolve("wx_local_app", attempt_id, media_id="wx_known_receipt_55")

        aid = self._create_article(
            title="Local Receipt Test",
            source_type="github",
            status="DRAFT_PENDING_RECORD",
            media_id="wx_known_receipt_55",
            success_status=True,
            error_log=f"local write interrupted [attempt_id={attempt_id}]",
        )
        local_accessor = webui._LocalDeliveryAccessor("wx_local_app", journal=journal)
        try:
            # Verify known-receipt reconcile succeeds purely locally even if _get_publisher would fail network
            with (
                patch.object(webui, "_get_delivery_accessor", return_value=local_accessor),
                patch.object(webui, "_get_publisher", side_effect=AssertionError("MUST NOT contact WeChat for known receipt!")),
            ):
                resp = client.post("/api/review/reconcile", json={"id": aid})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["backfilled"] is True
            assert data["draft_pushed"] is False
            assert data["review_status"] == "DRAFT"
            assert self._get_article(aid)["status"] == "DRAFT"
            assert journal.get("wx_local_app", attempt_id)["status"] == "DRAFT"

            # Idempotent replay on already-converged record stays 200 without contacting WeChat
            with (
                patch.object(webui, "_get_delivery_accessor", return_value=local_accessor),
                patch.object(webui, "_get_publisher", side_effect=AssertionError("MUST NOT contact WeChat!")),
            ):
                resp2 = client.post("/api/review/reconcile", json={"id": aid})
            assert resp2.status_code == 200
            assert resp2.get_json()["review_status"] == "DRAFT"
        finally:
            self._cleanup_article(aid)

    def test_draft_pending_record_backfills_first_and_never_recreates_draft(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        aid = self._create_article(
            title="Pending Record Aikepu Node",
            source_type="aikepu",
            source_url="aikepu://node/n_01",
            status="DRAFT_PENDING_RECORD",
            media_id="wx_existing_draft_77",
            success_status=True,
            error_log="skill_tree write failed",
        )
        try:
            mock_pub = MagicMock()
            mock_pub.access_token = "tok"
            mock_pub.pending_deliveries.return_value = []

            # Backfill fails -> must stay DRAFT_PENDING_RECORD and return 500, never call publish_and_notify
            with (
                patch.object(webui, "_get_publisher", return_value=mock_pub),
                patch("core.aikepu.skill_tree.mark_published", side_effect=RuntimeError("disk full")),
            ):
                resp_fail = client.post("/api/review/reconcile", json={"id": aid})
                assert resp_fail.status_code == 500
                assert self._get_article(aid)["status"] == "DRAFT_PENDING_RECORD"
                mock_pub.publish_and_notify.assert_not_called()

            # Backfill succeeds -> converges cleanly without ever calling publish_and_notify
            with (
                patch.object(webui, "_get_publisher", return_value=mock_pub),
                patch("core.aikepu.skill_tree.mark_published") as mock_mark,
            ):
                resp_ok = client.post("/api/review/approve", json={"id": aid})
                assert resp_ok.status_code == 200
                data = resp_ok.get_json()
                assert data["backfilled"] is True
                assert data["draft_pushed"] is False
                assert data["media_id"] == "wx_existing_draft_77"
                assert data["review_status"] == "APPROVED"
                mock_mark.assert_called_once()
                mock_pub.publish_and_notify.assert_not_called()
        finally:
            self._cleanup_article(aid)

    def test_approve_atomic_contention_allows_only_one_push(self, monkeypatch, tmp_path):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True

        aid = self._create_article(
            title="Concurrent Approve Race Article",
            status="PENDING_REVIEW",
        )
        preview_dir = os.path.join("data", "previews")
        os.makedirs(preview_dir, exist_ok=True)
        preview_file = os.path.join(preview_dir, f"{aid}.html")
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write("<p>race body</p>")

        entered = threading.Event()
        release = threading.Event()
        push_calls = []

        def slow_publish(title, html, thumb, digest="", *, operation_id=None, context=None):
            push_calls.append({"title": title, "operation_id": operation_id, "context": context})
            entered.set()
            release.wait(timeout=3)
            return True, {"media_id": "wx_atomic_1", "attempt_id": "att_atomic_1", "status": "DRAFT_PENDING_RECORD"}

        mock_pub = MagicMock()
        mock_pub.access_token = "tok"
        mock_pub.journal = None
        mock_pub.upload_image.return_value = "thumb_1"
        mock_pub.publish_and_notify.side_effect = slow_publish

        results = []

        def worker():
            c = webui.app.test_client()
            r = c.post("/api/review/approve", json={"id": aid})
            results.append((r.status_code, r.get_json()))

        try:
            with patch.object(webui, "_get_publisher", return_value=mock_pub):
                t1 = threading.Thread(target=worker)
                t2 = threading.Thread(target=worker)
                t1.start()
                assert entered.wait(timeout=3)
                t2.start()
                time.sleep(0.15)
                release.set()
                t1.join(timeout=5)
                t2.join(timeout=5)

            codes = sorted(r[0] for r in results)
            assert codes == [200, 409]
            assert len(push_calls) == 1
            assert push_calls[0]["operation_id"] == f"review_approve:{aid}"
            assert push_calls[0]["context"]["article_id"] == aid
            mock_pub.mark_delivery_recorded.assert_called_once_with("att_atomic_1")
            snap = self._get_article(aid)
            assert snap["status"] == "APPROVED"
            assert snap["media_id"] == "wx_atomic_1"
        finally:
            if os.path.exists(preview_file):
                os.remove(preview_file)
            self._cleanup_article(aid)

    def test_approve_push_failure_does_not_forge_approved(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        aid = self._create_article(title="Push Failure Honest Article", status="PENDING_REVIEW")
        preview_dir = os.path.join("data", "previews")
        os.makedirs(preview_dir, exist_ok=True)
        preview_file = os.path.join(preview_dir, f"{aid}.html")
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write("<p>body</p>")

        mock_pub = MagicMock()
        mock_pub.access_token = "tok"
        mock_pub.upload_image.return_value = "thumb_1"
        mock_pub.publish_and_notify.return_value = (False, {"errcode": 40007, "errmsg": "invalid thumb"})

        try:
            with patch.object(webui, "_get_publisher", return_value=mock_pub):
                resp = client.post("/api/review/approve", json={"id": aid})
            assert resp.status_code == 502
            data = resp.get_json()
            assert data["status"] == "error"
            assert "invalid thumb" in data["push_error"]
            snap = self._get_article(aid)
            assert snap["status"] == "FAILED"
            assert snap["success_status"] is False
        finally:
            if os.path.exists(preview_file):
                os.remove(preview_file)
            self._cleanup_article(aid)


class TestWebUISecurityAndFrontendContracts:
    def test_upload_rejects_path_traversal_index_before_writing(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        resp = client.post(
            "/api/image-studio/upload",
            data={"index": "../evil", "image": (BytesIO(b"fakepng"), "a.png")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_redraw_blocks_ssrf_private_and_loopback_urls(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        for bad_url in (
            "http://127.0.0.1:5000/api/config",
            "http://localhost/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
        ):
            resp = client.post("/api/image-studio/redraw", json={"article_url": bad_url})
            assert resp.status_code == 400, f"SSRF not blocked for {bad_url}"

    def test_schedule_add_validates_task_type_and_jobs_include_cron_expr(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        bad = client.post("/api/schedule/add", json={"task_type": "rm_rf", "cron_expr": "0 8 * * *"})
        assert bad.status_code == 400

        fake_job = SimpleNamespace(
            id="j1",
            name="Schedule_hotspots_0 8 * * *",
            kwargs={"task_type": "hotspots"},
            next_run_time=None,
            trigger=None,
        )
        with patch.object(webui.scheduler, "get_jobs", return_value=[fake_job]):
            jobs_resp = client.get("/api/schedule/jobs").get_json()
        assert jobs_resp["jobs"][0]["cron_expr"] == "0 8 * * *"

    def test_preview_escapes_wechat_title_xss(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        mock_pub = MagicMock()
        mock_pub.access_token = "tok"
        mock_pub.session.post.return_value.json.return_value = {
            "news_item": [{"title": "<script>alert(1)</script>", "content": "<p>ok</p>"}]
        }
        pid = "wx_xss_check_999"
        cache_path = os.path.join("data", "previews", f"{pid}.html")
        try:
            with patch.object(webui, "_get_publisher", return_value=mock_pub):
                resp = client.get(f"/api/preview/{pid}")
            assert resp.status_code == 200
            html_out = resp.get_data(as_text=True)
            assert "<script>alert(1)</script>" not in html_out
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
        finally:
            if os.path.exists(cache_path):
                os.remove(cache_path)

    def test_generate_node_validates_node_id_and_passes_override(self, monkeypatch):
        import webui

        monkeypatch.setattr(webui, "CLOUD_MODE", False)
        webui.ProcessState.set_running(False)
        webui.app.config["TESTING"] = True
        client = webui.app.test_client()

        fake_tree = {"nodes": [{"id": "n_01", "title": "Node 1"}]}
        with patch("core.aikepu.skill_tree.load_skill_tree", return_value=fake_tree):
            bad = client.post("/api/aikepu/generate_node", json={"node_id": "non_existent_node"})
            assert bad.status_code == 400

            started_args = {}

            class DummyThread:
                def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                    started_args["target"] = target
                    started_args["args"] = args
                    started_args["kwargs"] = kwargs or {}

                def start(self):
                    started_args["started"] = True

            with patch.object(webui.threading, "Thread", DummyThread):
                ok = client.post("/api/aikepu/generate_node", json={"node_id": "n_01"})
            assert ok.status_code == 200
            assert started_args.get("started") is True
            assert (
                started_args["kwargs"].get("override_node_id") == "n_01"
                or "n_01" in started_args["args"]
            )

    def test_frontend_contract_alignment_static_checks(self):
        with open("static/js/views/graph.js", "r", encoding="utf-8") as f:
            graph_js = f.read()
        with open("static/js/views/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()
        with open("static/js/views/audit.js", "r", encoding="utf-8") as f:
            audit_js = f.read()
        with open("static/js/core/state.js", "r", encoding="utf-8") as f:
            state_js = f.read()
        with open("static/js/core/api.js", "r", encoding="utf-8") as f:
            api_js = f.read()
        with open("static/js/views/ops.js", "r", encoding="utf-8") as f:
            ops_js = f.read()
        with open("static/js/views/studio.js", "r", encoding="utf-8") as f:
            studio_js = f.read()
        with open("templates/index.html", "r", encoding="utf-8") as f:
            index_html = f.read()

        # graph.js contracts
        assert "node.difficulty" in graph_js
        assert "tree.name" in graph_js
        assert "??" in graph_js

        # console.js & state.js contracts
        assert "PARTIAL_SUCCESS" in state_js
        assert "SKIPPED" in state_js
        assert "CANCELLED" in state_js
        assert "/api/status?since=" in console_js
        assert "last_run" in console_js
        assert "t.stats" in console_js
        assert "hit_tokens" in console_js

        # audit.js contracts
        assert "CLOUD_UNCERTAIN" in audit_js
        assert "DRAFT_PENDING_RECORD" in audit_js
        assert "/api/review/reconcile" in audit_js
        assert "a.preview_id" in audit_js

        # api.js FormData unique hash
        assert "body instanceof FormData" in api_js
        assert "return 'formdata';" not in api_js

        # ops.js custom select & escapeHtml
        assert "document.createElement('option')" in ops_js
        assert "escapeHtml(err.message)" in ops_js

        # studio.js XSS escaping
        assert "escapeHtml(msg)" in studio_js
        assert "escapeHtml(err.message)" in studio_js

        # index.html models
        assert "deepseek-v4-flash" in index_html
        assert "qwen-image-3.0" in index_html
        assert "imagen-3" not in index_html
