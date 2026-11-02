"""
pytest suite for WebUI Management Console E2E Interactions & Contracts
"""
import sys
import os
import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import verify_live_webui

def test_static_files_and_es_modules_serving():
    assert verify_live_webui.test_static_serving() is True

def test_all_es_modules_import_export_integrity():
    assert verify_live_webui.test_es_modules_import_export() is True

def test_all_five_stages_api_endpoints():
    assert verify_live_webui.test_api_endpoints() is True

@pytest.mark.asyncio
async def test_playwright_e2e_and_zero_browser_errors():
    ok, screenshots = await verify_live_webui.run_playwright_e2e()
    assert ok is True
    assert len(screenshots) == 10
