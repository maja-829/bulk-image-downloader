from typing import Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ProxyHandler:
    """
    Builds a configured requests.Session with optional proxies, UA, timeout, and retries.
    """

    def __init__(self, proxy_config: Optional[Dict] = None) -> None:
        self.proxy_config = proxy_config or {}

    def _build_retries(self) -> Retry:
        return Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"],
            raise_on_status=False,
        )

    def get_session(self, user_agent: str, timeout: int = 20) -> requests.Session:
        s = requests.Session()

        # Proxies
        if self.proxy_config.get("use_proxies"):
            proxies = {}
            if self.proxy_config.get("http"):
                proxies["http"] = self.proxy_config["http"]
            if self.proxy_config.get("https"):
                proxies["https"] = self.proxy_config["https"]
            if proxies:
                s.proxies.update(proxies)

        # UA + defaults
        s.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
            }
        )

        # Retries + timeouts via adapter
        retries = self._build_retries()
        adapter = HTTPAdapter(max_retries=retries, pool_connections=50, pool_maxsize=50)
        s.mount("http://", adapter)
        s.mount("https://", adapter)

        # Store default timeout (used explicitly by callers)
        s.request_timeout = timeout  # type: ignore[attr-defined]
        return s