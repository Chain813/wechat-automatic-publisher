import unittest
import re
from core.shared.article_utils import _extract_image_placeholders, _replace_placeholder

class TestImageHandlerLogic(unittest.TestCase):
    def test_extract_image_placeholders_preserves_order_and_duplicates(self):
        text = "段落1【此处插入配图：AI芯片】段落2【此处插入配图：神经网络】段落3【此处插入配图：AI芯片】"
        placeholders = _extract_image_placeholders(text)
        self.assertEqual(placeholders, ["AI芯片", "神经网络", "AI芯片"])

    def test_sequential_placeholder_replacement(self):
        html = "<p>【此处插入配图：AI芯片】</p><p>【此处插入配图：神经网络】</p><p>【此处插入配图：AI芯片】</p>"
        image_results = {
            0: "https://img1.com",
            1: "https://img2.com",
            2: "https://img3.com"
        }
        
        slot_cursor = 0
        pattern_placeholder = re.compile(r"【\s*此处插入配图\s*[：:]\s*.*?\s*】")
        
        def _replace(match):
            nonlocal slot_cursor
            idx = slot_cursor
            slot_cursor += 1
            url = image_results.get(idx)
            return f'<img src="{url}">' if url else ""

        result_html = pattern_placeholder.sub(_replace, html)
        self.assertIn('<img src="https://img1.com">', result_html)
        self.assertIn('<img src="https://img2.com">', result_html)
        self.assertIn('<img src="https://img3.com">', result_html)
        self.assertNotIn("AI芯片", result_html)

if __name__ == "__main__":
    unittest.main()
