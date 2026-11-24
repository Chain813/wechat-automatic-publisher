from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest
import yaml


@pytest.mark.parametrize("status,expected", [("success", 2), ("partial_success", 2), ("failed", 1)])
def test_encrypted_history_and_current_journal(tmp_path, status, expected):
    workflow = Path(__file__).parents[1] / ".github/workflows/trigger.yml"
    steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["publish"]["steps"]
    scripts = [step["run"].split("python - <<'PY'\n")[1].rsplit("\nPY", 1)[0]
               for step in steps if "python - <<'PY'\n" in step.get("run", "")]
    restore, pack = scripts
    env = dict(os.environ, WECHAT_APP_ID="account", WECHAT_APP_SECRET="secret",
               RUNNER_TEMP=str(tmp_path), GITHUB_OUTPUT=str(tmp_path / "output"), TASK_STATUS=status)
    if os.name == "nt" and not shutil.which("openssl"):
        git = Path(shutil.which("git")).resolve()
        openssl_dir = git.parent.parent / "usr" / "bin"
        env["PATH"] = str(openssl_dir) + os.pathsep + env["PATH"]
    for directory, value in [("previous-history", 1), ("data", 2)]:
        folder = tmp_path / directory
        folder.mkdir()
        for name in ("auto_publish.sqlite", "daily_knowledge.sqlite"):
            with closing(sqlite3.connect(folder / name)) as db, db:
                db.execute("CREATE TABLE history AS SELECT ? AS value", (value,))
    journal = tmp_path / "data/delivery.sqlite3"
    with closing(sqlite3.connect(journal)) as db, db:
        db.execute("CREATE TABLE delivery(account, attempt_id, status, context)")
        db.execute("INSERT INTO delivery VALUES ('account','a','CLOUD_UNCERTAIN','{}')")
    def run(script, **kwargs):
        return subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, **kwargs)

    run(pack, check=True)
    for path in (tmp_path / "data").iterdir():
        path.unlink()
    mac = tmp_path / ".autowechat_state/delivery.mac"
    valid = mac.read_bytes()
    mac.write_bytes(b"invalid")
    assert run(restore).returncode != 0
    assert not journal.exists()
    mac.write_bytes(valid)
    run(restore, check=True)
    for name in ("auto_publish.sqlite", "daily_knowledge.sqlite"):
        with sqlite3.connect(tmp_path / "data" / name) as db:
            assert db.execute("SELECT value FROM history").fetchone() == (expected,)
    with closing(sqlite3.connect(journal)) as db, db:
        assert db.execute("SELECT status FROM delivery").fetchone() == ("CLOUD_UNCERTAIN",)
