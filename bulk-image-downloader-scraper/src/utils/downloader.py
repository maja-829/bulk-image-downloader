import logging
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

class Downloader:
    """
    Concurrent file downloader with simple validation and robust error handling.
    """

    def __init__(
        self,
        session: requests.Session,
        concurrency: int = 8,
        timeout: int = 20,
        logger_name: str = "downloader",
    ) -> None:
        self.session = session
        self.concurrency = max(1, int(concurrency))
        self.timeout = timeout
        self.log = logging.getLogger(logger_name)

    def _safe_filename(self, url: str) -> str:
        # Strip querystrings/fragments and keep the tail
        tail = url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
        if not tail:
            tail = "image"
        # Ensure a minimal extension if missing
        if "." not in tail:
            tail += ".bin"
        return tail

    def _download_one(self, url: str, dest_dir: Path) -> Optional[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = self._safe_filename(url)
        target = dest_dir / filename

        try:
            with self.session.get(url, stream=True, timeout=self.timeout) as resp:
                resp.raise_for_status()
                # Minimal content-type guard
                ctype = resp.headers.get("Content-Type", "").lower()
                if "image" not in ctype and not any(
                    filename.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
                ):
                    self.log.debug(f"Skipping non-image content-type for {url}: {ctype}")
                    return None

                # Save stream
                with target.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)

            # Basic size check
            if target.stat().st_size <= 0:
                self.log.debug(f"Zero-byte file for {url}, removing.")
                target.unlink(missing_ok=True)
                return None

            return target

        except requests.RequestException as e:
            self.log.debug(f"Request failed for {url}: {e}")
        except Exception as e:
            self.log.debug(f"Unexpected error for {url}: {e}")
        return None

    def download_many(self, urls: Iterable[str], dest_dir: Path) -> List[Path]:
        urls = list(dict.fromkeys(urls))  # dedupe, keep order
        results: List[Path] = []
        if not urls:
            return results

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_map = {executor.submit(self._download_one, url, dest_dir): url for url in urls}
            for fut in as_completed(future_map):
                url = future_map[fut]
                try:
                    path = fut.result()
                    if path:
                        results.append(path)
                except Exception as e:
                    self.log.debug(f"Worker error for {url}: {e}")

        return results