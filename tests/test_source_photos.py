import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from PIL import Image, ImageDraw

from core.shared.runtime import WorkflowCancelled, cancel_event
from utils import source_photos


def item(**updates):
    record = {
        "title": "Observatory & telescope",
        "creator": "A. Photographer",
        "source": "flickr",
        "foreign_landing_url": "https://www.flickr.com/photos/observer/1234",
        "url": "https://live.staticflickr.com/42/1234_b.jpg",
        "license": "by",
        "license_version": "2.0",
        "license_url": "https://creativecommons.org/licenses/by/2.0/",
        "category": "photograph",
        "mature": False,
    }
    return {**record, **updates}


def response(data, *, status=200, **headers):
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers)
    result._content = data if isinstance(data, bytes) else json.dumps(data).encode()
    result._content_consumed = True
    return result


def image_bytes():
    image = Image.new("RGB", (1200, 800), "navy")
    # The two bands exercise the edges a center crop would discard.
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 60), fill="red")
    draw.rectangle((0, 740, 1199, 799), fill="lime")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


class SourcePhotoTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.photo = image_bytes()
        self.addCleanup(patch.stopall)
        self.send = patch.object(requests.Session, "send").start()

    def find(self, purpose="body"):
        return source_photos.find_source_photo("observatory", self.directory, purpose)

    def test_filters_records_then_downloads_first_licensed_photograph(self):
        records = [
            {},
            item(license="by-nc"),
            item(license_url="https://creativecommons.org/licenses/by-sa/2.0/"),
            item(license_version="4.0"),
            item(creator=""),
            item(category="illustration"),
            item(mature=True),
            item(url="https://live.staticflickr.com.example.com/x.jpg"),
            item(foreign_landing_url="javascript:example"),
            item(),
        ]
        self.send.side_effect = [response({"results": records}), response(self.photo)]
        found = self.find()
        self.assertEqual(found.creator, item()["creator"])
        self.assertEqual(found.title, item()["title"])
        self.assertEqual(found.source_url, item()["foreign_landing_url"])
        self.assertEqual(found.license_name, "CC BY 2.0")
        self.assertEqual(found.license_url, item()["license_url"])
        self.assertEqual(self.send.call_count, 2)
        search_url = self.send.call_args_list[0].args[0].url
        params = parse_qs(urlsplit(search_url).query)
        self.assertEqual(params["category"], ["photograph"])
        self.assertEqual(params["q"], ["observatory"])
        self.assertEqual(set(params["license"][0].split(",")), {"by", "cc0", "pdm"})
        self.assertEqual(self.send.call_args_list[1].args[0].url, item()["url"])
        with Image.open(found.path) as image:
            image.load()
            self.assertEqual((image.format, image.size), ("JPEG", (900, 600)))

    def test_full_frame_cover_survives_padding_and_multiple_calls(self):
        outputs = []
        for code, path in [("cc0", "zero"), ("pdm", "mark")]:
            license_url = f"https://creativecommons.org/publicdomain/{path}/1.0/"
            record = item(license=code, license_version="1.0", license_url=license_url)
            self.send.side_effect = [response({"results": [record]}), response(self.photo)]
            found = self.find("cover")
            self.assertEqual(found.license_url, license_url)
            outputs.append(found.path)
            with Image.open(found.path) as image:
                self.assertEqual(image.size, (900, 383))
                self.assertGreater(image.getpixel((450, 5))[0], 230)
                self.assertGreater(image.getpixel((450, 377))[1], 230)
        self.assertNotEqual(*outputs)

    def test_invalid_download_tries_another_result(self):
        record = item(
            source="wikimedia",
            url="https://upload.wikimedia.org/wikipedia/commons/f/f3/Observatory.jpg",
            foreign_landing_url="https://commons.wikimedia.org/wiki/File:Observatory.jpg",
        )
        self.send.side_effect = [
            response({"results": [item(), record]}),
            response(b"html or corrupt image"),
            response(self.photo),
        ]
        self.assertEqual(self.find().source_url, record["foreign_landing_url"])

    def test_existing_body_photo_generates_its_own_cover_without_a_search(self):
        body = self.directory / "body.jpg"
        body.write_bytes(self.photo)
        cover = source_photos.prepare_photo_cover(str(body), self.directory)
        self.assertNotEqual(Path(cover), body)
        self.assertEqual(body.read_bytes(), self.photo)
        with Image.open(cover) as image:
            self.assertEqual(image.size, (900, 383))
            self.assertGreater(image.getpixel((450, 5))[0], 230)
            self.assertGreater(image.getpixel((450, 377))[1], 230)
        self.send.assert_not_called()

    def test_provider_profile_page_is_not_accepted_as_the_work_page(self):
        record = item(foreign_landing_url="https://www.flickr.com/photos/observer/")
        self.send.side_effect = [response({"results": [record]}), response(self.photo)]
        self.assertIsNone(self.find())
        self.assertEqual(self.send.call_count, 1)

    def test_panorama_resized_for_body_can_still_be_reused_as_a_cover(self):
        output = io.BytesIO()
        Image.new("RGB", (2400, 240), "blue").save(output, format="JPEG")
        self.send.side_effect = [response({"results": [item()]}), response(output.getvalue())]
        photo = self.find()
        with Image.open(photo.path) as image:
            self.assertEqual(image.size, (900, 90))
        cover = source_photos.prepare_photo_cover(photo.path, self.directory)
        with Image.open(cover) as image:
            self.assertEqual(image.size, (900, 383))

    def test_solar_panels_rank_the_matching_subject_ahead_of_generic_results(self):
        records = [
            item(title="Project 365 #201: 200721 Harvest Time",
                 tags=[{"name": "rooftop"}, {"name": "solarfarm"}],
                 description="The display shows the output from rooftop solar panels."),
            item(title="Solar panels at park headquarters", tags=[{"name": "rooftop"}]),
            item(title="Install a roof top solar panel"),
        ]
        self.send.side_effect = [response({"results": records}), response(self.photo)]
        photo = source_photos.find_source_photo("rooftop solar panels", self.directory)
        self.assertEqual(photo.title, "Install a roof top solar panel")

    def test_tags_can_complete_a_title_that_already_names_the_subject(self):
        record = item(title="Solar panels at park headquarters", tags=[{"name": "rooftop"}])
        self.send.side_effect = [response({"results": [record]}), response(self.photo)]
        photo = source_photos.find_source_photo("rooftop solar panels", self.directory)
        self.assertEqual(photo.title, record["title"])

    def test_missing_subject_or_model_gets_no_photo(self):
        cases = [
            ("rooftop solar panels", "Harvest Time", ["rooftop", "solar", "panels"]),
            ("rooftop solar panels", "Panels on display", ["rooftop", "solar"]),
            ("Tesla Model 3", "Tesla Model S", ["tesla", "model", "electric"]),
            ("Tesla Model 3", "Tesla Model S", ["3", "tesla", "model"]),
            ("electric sports car", "Electric sports stadium", ["car"]),
            ("图书馆书架", "图书馆门口", ["图书馆", "照片"]),
        ]
        for query, title, tags in cases:
            with self.subTest(query=query, title=title):
                self.send.reset_mock()
                record = item(title=title, tags=[{"name": tag} for tag in tags], description=query)
                self.send.side_effect = [response({"results": [record]}), response(self.photo)]
                self.assertIsNone(source_photos.find_source_photo(query, self.directory))
                self.assertEqual(self.send.call_count, 1)

    def test_chinese_and_brand_subjects_match_title_variants(self):
        cases = [
            ("屋顶太阳能板", "村民在屋顶安装了太阳能板"),
            ("ＤＪＩ 无人机", "假日里的 DJI无人机"),
            ("NVIDIA H100", "NVIDIA H100 at the show"),
            ("library shelves", "A shelf in the library"),
        ]
        for query, title in cases:
            with self.subTest(query=query):
                self.send.side_effect = [response({"results": [item(title=title)]}), response(self.photo)]
                photo = source_photos.find_source_photo(query, self.directory)
                self.assertEqual(photo.title, title)

    def test_redirect_size_and_network_failure_leave_no_file(self):
        failures = [
            response(b"", status=302, Location="https://example.org/private"),
            response(self.photo, **{"Content-Length": str(256 * 1024 * 1024)}),
            requests.Timeout(),
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                self.send.side_effect = [response({"results": [item()]}), failure]
                self.assertIsNone(self.find())
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_or_malformed_results_and_network_errors(self):
        for body in [response(b"{"), response([]), response({"results": "a"}), requests.Timeout()]:
            with self.subTest(body=body):
                self.send.side_effect = [body]
                self.assertIsNone(self.find())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_rate_limit_cools_down_subsequent_search(self):
        with patch.object(source_photos, "_retry_at", 0):
            self.send.side_effect = [response(b"", status=429, **{"Retry-After": "600"})]
            self.assertIsNone(self.find())
            self.assertIsNone(self.find())
            self.assertEqual(self.send.call_count, 1)

    def test_cancel_skips_every_request(self):
        cancel_event.set()
        self.addCleanup(cancel_event.clear)
        with self.assertRaises(WorkflowCancelled):
            self.find()
        self.send.assert_not_called()
