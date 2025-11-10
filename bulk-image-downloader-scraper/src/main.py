import os
import sys
import json
import hashlib
import logging
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from typing import List, Dict, Any

# Ensure local imports work when executed as `python src/main.py`
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from utils.image_collector import ImageCollector
from utils.downloader import Downloader
from utils.proxy_handler import ProxyHandler

def setup_logging(verbosity: str = "INFO") -> None:
    level = getattr(logging, verbosity.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

def load_settings(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Settings file not found at: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        settings = json.load(f)

    # Environment overrides (optional)
    settings["concurrency"] = int(os.getenv("BID_CONCURRENCY", settings.get("concurrency", 8)))
    settings["timeout"] = int(os.getenv("BID_TIMEOUT", settings.get("timeout", 20)))
    settings["min_image_bytes"] = int(os.getenv("BID_MIN_IMAGE_BYTES", settings.get("min_image_bytes", 1024)))
    settings["user_agent"] = os.getenv("BID_USER_AGENT", settings.get("user_agent", "BulkImageDownloader/1.0"))

    # Proxy overrides
    proxy_env_http = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    proxy_env_https = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if proxy_env_http or proxy_env_https:
        settings.setdefault("proxies", {})
        settings["proxies"]["use_proxies"] = True
        if proxy_env_http:
            settings["proxies"]["http"] = proxy_env_http
        if proxy_env_https:
            settings["proxies"]["https"] = proxy_env_https

    return settings

def read_input_urls(input_file: Path) -> List[str]:
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found at: {input_file}")
    urls: List[str] = []
    with input_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls

def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)

def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def zip_directory(src_dir: Path, zip_path: Path) -> None:
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                zf.write(file, arcname=file.relative_to(src_dir))

def main() -> None:
    # Paths
    config_path = CURRENT_DIR / "config" / "settings.json"
    data_dir = PROJECT_ROOT / "data"
    archives_dir = data_dir / "archives"
    downloads_root = PROJECT_ROOT / "downloads"  # transient workspace
    input_file = data_dir / "input_urls.txt"
    output_file = data_dir / "sample_output.json"

    # Runtime setup
    settings = load_settings(config_path)
    setup_logging(settings.get("log_level", "INFO"))
    logger = logging.getLogger("main")

    ensure_dirs(data_dir, archives_dir, downloads_root)

    urls = read_input_urls(input_file)
    if not urls:
        logger.warning("No URLs found in input file. Add URLs to data/input_urls.txt (one per line).")
        return

    # Initialize helpers
    proxy_handler = ProxyHandler(settings.get("proxies", {}))
    session = proxy_handler.get_session(
        user_agent=settings.get("user_agent", "BulkImageDownloader/1.0"),
        timeout=settings.get("timeout", 20),
    )

    collector = ImageCollector(
        session=session,
        min_image_bytes=settings.get("min_image_bytes", 1024),
        logger_name="collector",
    )

    downloader = Downloader(
        session=session,
        concurrency=settings.get("concurrency", 8),
        timeout=settings.get("timeout", 20),
        logger_name="downloader",
    )

    results: List[Dict[str, str]] = []

    logger.info("Starting bulk image download...")
    for url in urls:
        try:
            url_hash = md5_hex(url)
            work_dir = downloads_root / url_hash
            ensure_dirs(work_dir)

            logger.info(f"[{url}] Collecting image URLs...")
            image_urls = collector.collect_image_urls(url)
            if not image_urls:
                logger.warning(f"[{url}] No images found.")
                continue

            logger.info(f"[{url}] Found {len(image_urls)} images. Downloading...")
            saved_files = downloader.download_many(image_urls, dest_dir=work_dir)

            if not saved_files:
                logger.warning(f"[{url}] No images successfully downloaded.")
                continue

            zip_path = archives_dir / f"{url_hash}.zip"
            logger.info(f"[{url}] Creating archive: {zip_path.name}")
            zip_directory(work_dir, zip_path)

            result_record = {
                "url": url,
                "urlHash": url_hash,
                "download": str(zip_path.resolve()),
            }
            results.append(result_record)
            logger.info(f"[{url}] Done. Archived {len(saved_files)} files.")
        except Exception as e:
            logger.exception(f"Failed processing {url}: {e}")

    if results:
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Wrote results to {output_file}")
    else:
        logger.warning("No results produced. Check logs for details.")

    # Cleanup workspace (optional: keep for debugging by setting keep_workspace)
    if not settings.get("keep_workspace", False):
        try:
            # Remove downloads directory tree
            for child in downloads_root.rglob("*"):
                if child.is_file():
                    child.unlink(missing_ok=True)
            # Remove empty directories bottom-up
            for directory in sorted(downloads_root.rglob("*"), reverse=True):
                if directory.is_dir():
                    directory.rmdir()
            downloads_root.rmdir()
        except Exception:
            logger.debug("Workspace cleanup skipped or partially completed.")

if __name__ == "__main__":
    main()