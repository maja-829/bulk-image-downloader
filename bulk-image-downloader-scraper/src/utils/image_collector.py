import logging
import re
from typing import List, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

_IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
_DATA_URL_RE = re.compile(r"^data:image/", re.IGNORECASE)

class ImageCollector:
    """
    Extracts image URLs from a webpage, handling src, srcset, and basic CSS background-image patterns.
    """

    def __init__(self, session: requests.Session, min_image_bytes: int = 1024, logger_name: str = "collector") -> None:
        self.session = session
        self.min_image_bytes = int(min_image_bytes)
        self.log = logging.getLogger(logger_name)

    def _is_http_url(self, url: str) -> bool:
        scheme = urlparse(url).scheme.lower()
        return scheme in ("http", "https")

    def _parse_srcset(self, srcset_value: str) -> List[str]:
        # srcset: "image1.jpg 1x, image2.jpg 2x" -> extract URLs
        urls: List[str] = []
        for part in srcset_value.split(","):
            url = part.strip().split(" ")[0].strip()
            if url:
                urls.append(url)
        return urls

    def _extract_from_inline_styles(self, soup: BeautifulSoup) -> List[str]:
        urls: List[str] = []
        for tag in soup.find_all(style=True):
            style = tag["style"]
            # rudimentary background-image: url('...') detection
            matches = re.findall(r"url\((['\"]?)(.+?)\1\)", style, flags=re.IGNORECASE)
            for _, found in matches:
                urls.append(found)
        return urls

    def _filter_image_like(self, url: str) -> bool:
        if _DATA_URL_RE.match(url):
            return False
        lower = url.lower()
        if any(lower.endswith(ext) for ext in _IMG_EXTS):
            return True
        # allow content-type validation later for URLs without extension
        return True

    def _validate_image_head(self, url: str) -> bool:
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=10)
            ctype = resp.headers.get("Content-Type", "").lower()
            if "image" in ctype:
                return True
            # If no content-type or not image, we still might allow download if extension suggests image
            return any(url.lower().endswith(ext) for ext in _IMG_EXTS)
        except requests.RequestException:
            return False

    def collect_image_urls(self, page_url: str) -> List[str]:
        urls: Set[str] = set()
        try:
            resp = self.session.get(page_url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.log.warning(f"Failed to fetch page {page_url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # <img src=...> and <img srcset=...>
        for img in soup.find_all("img"):
            if img.has_attr("src"):
                urls.add(img["src"])
            if img.has_attr("srcset"):
                urls.update(self._parse_srcset(img["srcset"]))

        # Inline styles with background-image
        urls.update(self._extract_from_inline_styles(soup))

        # Resolve relative URLs and filter
        resolved: List[str] = []
        for u in urls:
            abs_url = urljoin(page_url, u)
            if self._is_http_url(abs_url) and self._filter_image_like(abs_url):
                resolved.append(abs_url)

        # Optionally validate with HEAD (keeps performance reasonable)
        validated: List[str] = []
        for u in resolved:
            if self._validate_image_head(u):
                validated.append(u)

        # Keep stable order while de-duplicating
        seen: Set[str] = set()
        ordered = []
        for u in validated:
            if u not in seen:
                ordered.append(u)
                seen.add(u)
        return ordered