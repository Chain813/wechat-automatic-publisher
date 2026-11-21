from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from core.shared.article_utils import process_article_content


def test_photo_slots_credit_the_original_work_and_reuse_cover():
    from core.shared import article_photos

    def find_photo(query, directory):
        if query == "missing":
            return None
        path = Path(directory) / "solar.jpg"
        Image.new("RGB", (640, 420)).save(path)
        return SimpleNamespace(path=str(path), title="Solar <roof>", creator="A & B",
                               source_url="https://example.org/work/42",
                               license_name="CC BY 4.0", license_url="https://creativecommons.org/licenses/by/4.0/")

    publisher = Mock()
    publisher.upload_news_image.return_value = "https://mmbiz.qpic.cn/photo.jpg"
    publisher.upload_image.return_value = "cover-id"
    article = "开头。\n\n【此处插入配图：missing】\n\n第二段。\n\n【此处插入配图：solar panel】"
    article += "\n\n【此处插入配图：solar panel】"
    with patch.object(article_photos, "find_source_photo", side_effect=find_photo) as lookup, \
         patch.object(article_photos, "download_image", return_value=None) as generate:
        body, stats = process_article_content(article, publisher, cover_title="屋顶光伏")
    assert lookup.call_count == 2
    assert [call.args[0] for call in generate.call_args_list] == ["missing"]
    assert stats["thumb_id"] == "cover-id"
    assert stats["image_count"] == 1
    assert body.index("第二段") < body.index("<img")
    assert "A &amp; B" in body and "Solar &lt;roof&gt;" in body
    assert "https://example.org/work/42" in body and "CC BY 4.0" in body
    assert "封面" in body and "【此处" not in body
    publisher.upload_news_image.assert_called_once()
    assert not Path(publisher.upload_news_image.call_args.args[0]).exists()


def test_missing_photo_leaves_text_and_uses_title_card():
    from core.shared import article_photos

    publisher = Mock()
    publisher.upload_image.return_value = "card-id"
    with patch.object(article_photos, "find_source_photo", return_value=None), \
         patch.object(article_photos, "download_image", return_value=None):
        body, stats = process_article_content("正文。\n\n【此处插入配图：missing】", publisher, cover_title="屋顶光伏")
    assert stats["thumb_id"] == "card-id" and stats["image_count"] == 0
    assert "正文" in body and "【此处" not in body and "图片来源" not in body
    publisher.upload_news_image.assert_not_called()
    assert "AI 示意图" not in body


def test_generated_illustration_is_labelled_in_body_and_on_cover():
    from core.shared import article_photos
    from PIL import ImageDraw

    def generate(keyword, directory, *, allow_title_card):
        assert keyword == "edge device" and not allow_title_card
        Path(directory).mkdir(parents=True, exist_ok=True)
        path = Path(directory) / "illustration.jpg"
        Image.new("RGB", (640, 420), "steelblue").save(path)
        return str(path)

    publisher = Mock()
    publisher.upload_news_image.return_value = "https://mmbiz.qpic.cn/illustration.jpg"
    publisher.upload_image.return_value = "ai-cover"
    with patch.object(article_photos, "find_source_photo", return_value=None), \
         patch.object(article_photos, "download_image", side_effect=generate) as generate_image, \
         patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=ImageDraw.ImageDraw.text) as draw:
        body, stats = process_article_content("正文。\n\n【此处插入配图：edge device】", publisher, cover_title="端侧推理")
    assert stats["thumb_id"] == "ai-cover" and stats["image_count"] == 1
    assert "AI 示意图" in body and "资料图" not in body
    assert body.index("illustration.jpg") < body.index("AI 示意图")
    assert "AI 示意图" in [call.args[2] for call in draw.call_args_list]
    generate_image.assert_called_once()


def test_later_real_photo_gets_cover_and_only_missing_slot_gets_ai_caption(tmp_path):
    from bs4 import BeautifulSoup
    from core.shared import article_photos

    real = tmp_path / "original.jpg"
    Image.new("RGB", (640, 420), "green").save(real)
    photo = SimpleNamespace(path=str(real), title="Rooftop panels", creator="Lin",
                            source_url="https://example.org/solar", license_name="CC BY 4.0",
                            license_url="https://creativecommons.org/licenses/by/4.0/")
    publisher = Mock()
    publisher.upload_news_image.side_effect = lambda path: "https://mmbiz.qpic.cn/" + Path(path).name
    publisher.upload_image.return_value = "photo-cover"
    article = "开头。\n\n【此处插入配图：missing】\n\n实拍。\n\n【此处插入配图：panels】"
    with patch.object(article_photos, "find_source_photo", side_effect=lambda kw, _: photo if kw == "panels" else None), \
         patch.object(article_photos, "download_image", return_value="illustration.jpg") as generate, \
         patch.object(article_photos, "label_ai_cover") as label:
        body, stats = process_article_content(article, publisher, cover_title="光伏板")
    assert stats["image_count"] == 2 and stats["thumb_id"] == "photo-cover"
    figures = BeautifulSoup(body, "html.parser").find_all("img")
    assert figures[0]["src"].endswith("illustration.jpg")
    assert figures[0].parent.find_next_sibling("p").get_text() == "AI 示意图"
    assert "封面及正文资料图" in figures[1].parent.find_next_sibling("p").get_text()
    assert generate.call_count == 1 and generate.call_args.args[0] == "missing"
    label.assert_not_called()


def test_model_only_download_never_returns_local_title_card(tmp_path):
    from utils import image_handler

    with patch.object(image_handler, "_get_qwen_key_pool", return_value=SimpleNamespace(size=0)), \
         patch.object(image_handler, "SD_ENABLED", False), \
         patch.object(image_handler, "generate_default_cover") as card:
        assert image_handler.download_image("storage", tmp_path, allow_title_card=False) is None
    card.assert_not_called()


def test_cover_only_decodes_qwen_result_and_adds_disclosure():
    import base64
    from io import BytesIO
    from core.shared import article_photos
    from utils import image_handler

    png = BytesIO()
    Image.new("RGB", (900, 500), "teal").save(png, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode("ascii")
    response = {"output": {"choices": [{"message": {"content": [{"image": data_uri}]}}]}}
    publisher = Mock()
    def upload_cover(path):
        with Image.open(path) as image:
            assert image.size == (900, 383)
        return "qwen-cover"
    publisher.upload_image.side_effect = upload_cover
    image_handler.reset_image_cache()
    try:
        with patch.object(article_photos, "find_source_photo", return_value=None), \
             patch.object(image_handler, "_get_qwen_key_pool", return_value=SimpleNamespace(size=1)), \
             patch.object(image_handler, "_qwen_post_with_rotation", return_value=(200, response)) as post:
            body, stats = process_article_content("本文无正文插图。", publisher, cover_title="只配封面的文章")
    finally:
        image_handler.reset_image_cache()
    assert stats["thumb_id"] == "qwen-cover" and stats["image_count"] == 0
    assert "AI 示意图" in body
    post.assert_called_once()
    publisher.upload_news_image.assert_not_called()


def test_github_uploaded_screenshot_uses_original_page_as_credit():
    cdn = "https://mmbiz.qpic.cn/screenshot/q1"
    page = "https://github.com/example/project#readme"
    publisher = Mock()
    with patch("core.shared.article_utils.requests.get") as download:
        body, stats = process_article_content(
            f"项目截图\n\n【GITHUB配图：{cdn}】\n\n【GITHUB配图：https://example.net/unlisted.jpg】",
            publisher, github_sources={cdn: page},
        )
    download.assert_not_called()
    publisher.upload_news_image.assert_not_called()
    assert stats["image_count"] == 1 and page in body and cdn in body
    assert "图片来源" in body and "unlisted" not in body


def test_collection_keeps_project_page_after_rehosting_screenshot(tmp_path):
    from core.github import workflow

    screenshot = tmp_path / "readme.png"
    Image.new("RGB", (320, 180)).save(screenshot)
    project = {"repo": "example/project"}
    publisher = Mock()
    cdn = "https://mmbiz.qpic.cn/project-preview"
    publisher.upload_news_image.return_value = cdn
    with patch.object(workflow, "take_github_readme_screenshot", return_value=str(screenshot)), \
         patch.object(workflow, "get_repo_code_snippet", return_value=("", "")):
        workflow._ensure_deep_images([project], publisher)
    assert project["image_urls"] == [cdn]
    assert project["image_sources"] == {cdn: "https://github.com/example/project#readme"}
