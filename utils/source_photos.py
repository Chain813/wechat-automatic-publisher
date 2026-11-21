"""Find attributable photographs in Openverse and fit their full frame to WeChat."""
from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from loguru import logger
from PIL import Image, ImageOps
from requests import RequestException
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

from config import WECHAT_BODY_WIDTH, WECHAT_COVER_HEIGHT, WECHAT_COVER_WIDTH
from core.shared.runtime import check_cancelled
from utils.http_client import build_api_session


@dataclass(frozen=True)
class SourcePhoto:
    path: str
    title: str
    creator: str
    source_url: str
    license_name: str
    license_url: str


_API_URL = "https://api.openverse.org/v1/images/"
_PHOTO_HOSTS = {
    "flickr": ({"flickr.com", "www.flickr.com"}, {"live.staticflickr.com"}),
    "wikimedia": ({"commons.wikimedia.org"}, {"upload.wikimedia.org"}),
}
_search_lock = threading.Lock()
_download_slots = threading.BoundedSemaphore(3)
_retry_at = 0.0
_HAN = re.compile(r"[\u3400-\u9fff]+")
_IGNORE_QUERY_WORDS = set("a an and at by for from in of on the to with photo photograph image picture".split())
_IRREGULAR_PLURALS = {"shelves": "shelf", "leaves": "leaf", "knives": "knife", "wolves": "wolf"}


def _https_url(url, hosts):
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\\\x00-\x1f]", url):
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.netloc.lower() in hosts and parsed.path not in ("", "/"):
            return url
    except ValueError:
        pass
    return ""


def _work_page(page, source):
    parsed = urlsplit(page)
    if source == "flickr":
        return re.fullmatch(r"/photos/[^/]+/\d+/?", parsed.path)
    if parsed.path == "/w/index.php":
        return any(value.isdecimal() for value in parse_qs(parsed.query).get("curid", []))
    return re.fullmatch(r"/wiki/(File|Image):.+", unquote(parsed.path), re.IGNORECASE)


def _credits(record):
    if not isinstance(record, dict) or record.get("category") != "photograph" or record.get("mature"):
        return None
    source = record.get("source")
    if not isinstance(source, str) or source not in _PHOTO_HOSTS:
        return None
    pages, files = _PHOTO_HOSTS[source]
    page = _https_url(record.get("foreign_landing_url"), pages)
    if not page or not _work_page(page, source) or not _https_url(record.get("url"), files):
        return None
    title, creator = record.get("title"), record.get("creator")
    if not all(isinstance(value, str) and value.strip() for value in (title, creator)):
        return None

    code, version = record.get("license"), record.get("license_version")
    if code == "by" and version in ("1.0", "2.0", "2.5", "3.0", "4.0"):
        name, license_path = f"CC BY {version}", f"licenses/by/{version}"
    elif code == "cc0" and version == "1.0":
        name, license_path = "CC0 1.0", "publicdomain/zero/1.0"
    elif code == "pdm" and version == "1.0":
        name, license_path = "Public Domain Mark 1.0", "publicdomain/mark/1.0"
    else:
        return None
    license_url = _https_url(record.get("license_url"), {"creativecommons.org"})
    if license_url.rstrip("/") != f"https://creativecommons.org/{license_path}":
        return None
    return {
        "title": title.strip(),
        "creator": creator.strip(),
        "source_url": page,
        "license_name": name,
        "license_url": license_url,
    }


def _singular(word):
    if not word.isascii() or not word.isalpha():
        return word
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "ics")):
        return word[:-1]
    return word


def _words(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    separated = _HAN.sub(r" \g<0> ", normalized)
    return [_singular(word) for word in re.findall(r"[^\W_]+", separated)]


def _title_matches(terms, title_words):
    # Adjacent words cover spelling variants such as "roof top" and "rooftop".
    forms = set(title_words)
    forms.update(left + right for left, right in zip(title_words, title_words[1:]))
    matched = terms & forms
    text = " ".join(title_words)
    for term in terms - matched:
        if len(term) < 2 or not _HAN.fullmatch(term):
            continue
        # Chinese titles often insert a short qualifier between two subject names.
        if term in text or any(
            re.search(term[:split] + r".{0,6}" + term[split:], text)
            for split in range(2, len(term) - 1)
        ):
            matched.add(term)
    return matched


def _ranked_candidates(records, query):
    query_words = [word for word in _words(query[:200]) if word not in _IGNORE_QUERY_WORDS]
    if not query_words:
        return []
    terms = set(query_words)
    candidates = []
    for record in records:
        credit = _credits(record)
        if not credit:
            continue
        title_words = _words(credit["title"][:1000])
        in_title = _title_matches(terms, title_words)
        # Every query term needs evidence. A tag can supply a qualifier only
        # when the title names the trailing noun/model and two thirds of the terms.
        if query_words[-1] not in in_title or len(in_title) * 3 < len(terms) * 2:
            continue
        tags = record.get("tags")
        tag_words = {
            word for tag in (tags if isinstance(tags, list) else [])
            if isinstance(tag, dict) and isinstance(tag.get("name"), str)
            for word in _words(tag["name"])
        }
        if terms - in_title - tag_words:
            continue
        phrase_in_title = "".join(query_words) in "".join(title_words)
        candidates.append(((len(in_title), phrase_in_title), record["url"], credit))
    return sorted(candidates, key=lambda candidate: candidate[0], reverse=True)


def _read_bounded(response, max_bytes):
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    if int(response.headers.get("Content-Length", 0)) > max_bytes:
        raise ValueError("response too large")
    data = bytearray()
    deadline = time.monotonic() + 12
    for chunk in response.iter_content(64 * 1024):
        check_cancelled()
        if len(data) + len(chunk) > max_bytes or time.monotonic() > deadline:
            raise ValueError("response exceeded size or time limit")
        data.extend(chunk)
    return data


def _search(session, query):
    global _retry_at
    params = {
        "q": query[:200],
        "category": "photograph",
        "license": "by,cc0,pdm",
        "source": ",".join(_PHOTO_HOSTS),
        "page_size": 10,
    }
    # A throttled search should immediately yield to the article's other image options.
    with _search_lock:
        check_cancelled()
        if time.monotonic() < _retry_at:
            return []
        with session.get(_API_URL, params=params, stream=True, timeout=(3, 6), allow_redirects=False) as response:
            if response.status_code == 429:
                try:
                    delay = Retry().get_retry_after(response)
                except InvalidHeader:
                    delay = None
                _retry_at = time.monotonic() + (delay or 60)
                logger.info("Openverse 检索已限流，暂用其他配图")
                return []
            body = json.loads(_read_bounded(response, 512 * 1024))
    records = body.get("results") if isinstance(body, dict) else None
    return records[:10] if isinstance(records, list) else []


def _save_photo(raw, directory, purpose):
    if raw.width * raw.height > 24_000_000:
        raise ValueError("photograph exceeds pixel limit")
    image = ImageOps.exif_transpose(raw).convert("RGB")
    if purpose == "cover":
        image = ImageOps.pad(
            image, (WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT),
            method=Image.Resampling.LANCZOS, color="white",
        )
    else:
        image.thumbnail((WECHAT_BODY_WIDTH, 1600), Image.Resampling.LANCZOS)

    # Encode before creating the file so an invalid image cannot leave a partial upload.
    jpeg = io.BytesIO()
    image.save(jpeg, "JPEG", quality=88, optimize=True)
    check_cancelled()
    Path(directory).mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="source_photo_", suffix=".jpg", dir=directory, delete=False) as output:
        path = Path(output.name)
        try:
            output.write(jpeg.getbuffer())
            output.flush()
        except OSError:
            output.close()
            path.unlink(missing_ok=True)
            raise
    return str(path)


def prepare_photo_cover(path: str, directory: str | Path) -> str:
    """Create a separate padded cover from a selected local photograph."""
    with Image.open(path, formats=("JPEG", "PNG", "WEBP")) as image:
        return _save_photo(image, directory, "cover")


def find_source_photo(query: str, directory: str | Path, purpose: str = "body") -> SourcePhoto | None:
    """Return a downloaded photo with its creator, work page and license, or None."""
    check_cancelled()
    if not isinstance(query, str) or not query.strip():
        return None
    with _download_slots, build_api_session() as session:
        # The shared session normally retries 429 and 5xx. An optional illustration
        # must be able to fall back without sleeping through a remote Retry-After.
        session.get_adapter(_API_URL).max_retries = Retry(total=0)
        try:
            records = _search(session, query.strip())
        except (RequestException, ValueError) as error:
            logger.warning("Openverse 图片检索失败：{}", error)
            return None
        tried = set()
        for _, image_url, credits in _ranked_candidates(records, query):
            check_cancelled()
            if image_url in tried:
                continue
            tried.add(image_url)
            try:
                with session.get(image_url, stream=True, timeout=(3, 6), allow_redirects=False) as response:
                    data = _read_bounded(response, 12 * 1024 * 1024)
                with Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
                    if min(image.size) < 160 or max(image.size) < 480:
                        raise ValueError("photograph too small")
                    path = _save_photo(image, directory, purpose)
                return SourcePhoto(path=path, **credits)
            except (RequestException, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
                logger.debug("跳过不可用的 Openverse 图片：{}", error)
            if len(tried) >= 3:
                break
    return None
