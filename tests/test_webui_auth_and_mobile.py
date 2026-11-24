import os
import sys
import re
from urllib.parse import quote

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import webui


def test_cloud_auth_routes_and_no_store_cache_headers(monkeypatch):
    monkeypatch.setattr(webui, "CLOUD_MODE", True)
    monkeypatch.setattr(webui, "WEBUI_TOKEN", "tok+abc/123")
    webui.app.config["TESTING"] = True
    client = webui.app.test_client()

    # 1. Unauthenticated GET / renders login.html with no-store
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "login-form" in res_root.get_data(as_text=True)
    assert "no-store" in res_root.headers.get("Cache-Control", "")
    assert res_root.headers.get("Pragma") == "no-cache"

    # 2. Unauthenticated HEAD / returns 200 HTML, not 401 JSON
    res_head = client.head("/")
    assert res_head.status_code == 200
    assert "no-store" in res_head.headers.get("Cache-Control", "")

    # 3. Unauthenticated GET /login and HEAD /login render login.html (200, not 401)
    res_login = client.get("/login")
    assert res_login.status_code == 200
    assert "login-form" in res_login.get_data(as_text=True)
    assert "no-store" in res_login.headers.get("Cache-Control", "")

    res_login_head = client.head("/login")
    assert res_login_head.status_code == 200

    # 4. Unauthenticated protected API returns 401 JSON with no-store
    res_cfg_unauth = client.get("/api/config")
    assert res_cfg_unauth.status_code == 401
    assert "no-store" in res_cfg_unauth.headers.get("Cache-Control", "")

    # 5. Health check /api/status remains exempt
    res_status = client.get("/api/status")
    assert res_status.status_code == 200

    # 6. Authenticated with URL-encoded cookie (as main.js encodes via encodeURIComponent)
    encoded = quote("tok+abc/123", safe="")
    client.set_cookie("aw_token", encoded)

    res_cfg_auth = client.get("/api/config")
    assert res_cfg_auth.status_code == 200

    res_root_auth = client.get("/")
    assert res_root_auth.status_code == 200
    assert "view-console" in res_root_auth.get_data(as_text=True)
    assert "no-store" in res_root_auth.headers.get("Cache-Control", "")

    # 7. Authenticated GET /login redirects back to /
    res_login_auth = client.get("/login")
    assert res_login_auth.status_code == 302
    assert res_login_auth.headers["Location"].endswith("/")


def test_mobile_scroll_and_touch_target_contracts():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(repo_root, "static/css/tokens.css"), "r", encoding="utf-8") as f:
        tokens_css = f.read()
    with open(os.path.join(repo_root, "static/css/views.css"), "r", encoding="utf-8") as f:
        views_css = f.read()
    with open(os.path.join(repo_root, "static/css/components.css"), "r", encoding="utf-8") as f:
        components_css = f.read()
    with open(os.path.join(repo_root, "static/js/core/api.js"), "r", encoding="utf-8") as f:
        api_js = f.read()
    with open(os.path.join(repo_root, "static/js/main.js"), "r", encoding="utf-8") as f:
        main_js = f.read()

    # html/body must NOT trap viewport at height: 100% + overflow-x: hidden
    root_block_match = re.search(r"html,\s*body\s*\{[^}]*\}", tokens_css)
    if root_block_match:
        block = root_block_match.group(0)
        assert "height: 100%" not in block, "html, body height: 100% breaks mobile document scroll"
        assert "overflow-x: hidden" not in block, "overflow-x: hidden on html, body forces inner scroll container"

    assert "overflow-x: clip" in tokens_css

    # Raw log panel must expand naturally on mobile without nested scroll trap & stack vertically
    assert "max-height: none" in views_css
    assert "flex-direction: column" in views_css
    # Mobile log priority & touch targets >= 44px
    assert ".side-card-stream" in views_css
    assert ".mode-toggle-btn" in components_css or ".mode-toggle-btn" in views_css
    assert "min-height: 44px" in views_css
    assert "1180px" in components_css

    # Redirect target must use /login via replace to defeat stale cached /
    assert "/login" in api_js
    assert "window.location.replace('/login')" in api_js
    assert "pageshow" in main_js
    assert "visibilitychange" in main_js


def test_cloud_blank_token_fails_closed_and_local_mode_stays_open(monkeypatch):
    monkeypatch.setattr(webui, "CLOUD_MODE", True)
    monkeypatch.setattr(webui, "WEBUI_TOKEN", "   ")
    client = webui.app.test_client()
    health = client.get("/api/status?since=0")
    assert health.status_code == 200
    assert set(health.json) == {"is_running", "is_paused", "logs"}
    assert health.json["logs"] == []
    assert client.get("/api/config").status_code == 503
    assert client.post("/api/start?token=anything").status_code == 503
    assert client.get("/").status_code == 503
    monkeypatch.setattr(webui, "CLOUD_MODE", False)
    assert client.get("/api/config").status_code == 200
