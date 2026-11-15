import os
import sys
import re
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from webui import app


class TestWebUIRefactorContracts:
    """前端重构契约与质量门禁测试套件"""

    EMOJI_PATTERN = re.compile(
        r"[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]"
    )

    EXPECTED_CORE_MODULES = [
        "icons.js",
        "storage.js",
        "api.js",
        "state.js",
        "i18n.js",
        "log-parser.js",
    ]

    EXPECTED_VIEW_MODULES = [
        "console.js",
        "graph.js",
        "audit.js",
        "studio.js",
        "ops.js",
    ]

    def test_templates_have_no_inline_styles_and_link_modular_assets(self):
        """测试 index.html 和 login.html 不含内联 style，且引入版本化模块静态文件"""
        for template_name in ["templates/index.html", "templates/login.html"]:
            assert os.path.exists(template_name), f"缺少必要模板: {template_name}"
            with open(template_name, "r", encoding="utf-8") as f:
                content = f.read()

            # 禁止内联 <style> 块
            assert "<style>" not in content, f"{template_name} 包含内联 <style>，违反模块化规范"
            # 禁止引用已废弃的 three.js 资产
            assert "three.min.js" not in content, f"{template_name} 仍包含废弃 three.min.js"
            assert "three-bg.js" not in content, f"{template_name} 仍包含废弃 three-bg.js"

        # 检查 index.html 专属引入
        with open("templates/index.html", "r", encoding="utf-8") as f:
            index_content = f.read()
        assert "/static/css/tokens.css?v=2026" in index_content
        assert "/static/css/components.css?v=2026" in index_content
        assert "/static/css/views.css?v=2026" in index_content
        assert 'type="module"' in index_content
        assert "/static/js/main.js?v=2026" in index_content

    def test_zero_emojis_in_frontend_code(self):
        """测试 templates/, static/css/, static/js/ 中不存在任何系统 Emoji"""
        target_dirs = ["templates", "static/css", "static/js"]
        violating_files = []

        for target_dir in target_dirs:
            if not os.path.exists(target_dir):
                continue
            for root, _, files in os.walk(target_dir):
                for file_name in files:
                    if file_name.endswith((".html", ".css", ".js")):
                        file_path = os.path.join(root, file_name)
                        # 跳过即将删除的废弃资产
                        if any(legacy in file_name for legacy in ["three", "app.js", "style.css", "image-studio"]):
                            continue
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                        matches = self.EMOJI_PATTERN.findall(text)
                        if matches:
                            violating_files.append((file_path, matches))

        assert len(violating_files) == 0, f"发现文件中存在 Emoji 字符: {violating_files}"

    def test_modules_exist_and_under_400_loc(self):
        """测试全部 12 个 ES 模块均存在且非空/非注释代码行数严格小于 400 行"""
        base_dir = "static/js"

        for mod in self.EXPECTED_CORE_MODULES:
            path = os.path.join(base_dir, "core", mod)
            assert os.path.exists(path), f"缺少核心模块: {path}"
            self._verify_loc(path)

        for mod in self.EXPECTED_VIEW_MODULES:
            path = os.path.join(base_dir, "views", mod)
            assert os.path.exists(path), f"缺少视图模块: {path}"
            self._verify_loc(path)

        entry_path = os.path.join(base_dir, "main.js")
        assert os.path.exists(entry_path), f"缺少入口模块: {entry_path}"
        self._verify_loc(entry_path)

    def _verify_loc(self, path):
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("//")]
        assert len(lines) < 400, f"模块代码行数超标 (>400 行): {path} ({len(lines)} 行)"

    def test_flask_webui_routes_smoke(self):
        """测试 Flask WebUI 核心路由连通性"""
        app.config["TESTING"] = True
        client = app.test_client()

        # 访问根路径
        res_root = client.get("/")
        assert res_root.status_code in [200, 401]

        res_status = client.get("/api/status")
        assert res_status.status_code == 200
        status_json = res_status.get_json()
        assert "is_running" in status_json
        assert "logs" in status_json

    def test_js_dom_ids_exist_in_templates(self):
        """测试 static/js/views/*.js 中所有静态 getElementById 的 ID 均在 templates/index.html 中存在定义"""
        with open("templates/index.html", "r", encoding="utf-8") as f:
            index_html = f.read()
        template_ids = set(re.findall(r'id=["\']([^"\']+)["\']', index_html))

        missing_by_module = {}
        views_dir = "static/js/views"
        for mod in self.EXPECTED_VIEW_MODULES:
            path = os.path.join(views_dir, mod)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            js_ids = set(re.findall(r"getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", content))
            diff = js_ids - template_ids
            if diff:
                missing_by_module[mod] = sorted(diff)

        assert len(missing_by_module) == 0, f"发现视图模块引用的 DOM ID 在 templates/index.html 中缺失: {missing_by_module}"

        # 检查 main.js 引用的 ID 在 index.html 或 login.html 中存在定义
        with open("templates/login.html", "r", encoding="utf-8") as f:
            login_html = f.read()
        all_template_ids = template_ids | set(re.findall(r'id=["\']([^"\']+)["\']', login_html))
        with open("static/js/main.js", "r", encoding="utf-8") as f:
            main_content = f.read()
        main_ids = set(re.findall(r"getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", main_content))
        diff_main = main_ids - all_template_ids
        assert len(diff_main) == 0, f"发现 main.js 引用的 DOM ID 缺失: {diff_main}"


