import asyncio
import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ForumAuthService:
    def __init__(
        self,
        *,
        forum_root_url: str,
        forum_login_url: str,
        username: str,
        password: str,
        timeout_seconds: int,
        user_agent: str,
        fallback_cookie: str = "",
        preferred_cookie_name: str = "xf_session",
    ):
        self.forum_root_url = forum_root_url
        self.forum_login_url = forum_login_url
        self.username = username.strip()
        self.password = password.strip()
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.fallback_cookie = fallback_cookie.strip()
        self.preferred_cookie_name = preferred_cookie_name.strip()

        self._cookie_lock = asyncio.Lock()
        self._cached_cookie = "" if (self.username and self.password) else self.fallback_cookie

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def _resolve_login_url(self) -> str:
        if self.forum_login_url:
            return self.forum_login_url
        parsed = urlparse(self.forum_root_url)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/forum/login/"

    @staticmethod
    def _extract_form_payload(html: str, page_url: str) -> tuple[str, dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        form = soup.select_one("form[action*='login/login']")
        if not form:
            for candidate in soup.select("form"):
                if candidate.select_one("input[name='login']") and candidate.select_one("input[name='password']"):
                    form = candidate
                    break
        if not form:
            return "", {}

        action = form.get("action") or page_url
        action_url = urljoin(page_url, action)

        payload: dict[str, str] = {}
        for input_tag in form.select("input[name]"):
            name = (input_tag.get("name") or "").strip()
            if not name:
                continue
            input_type = (input_tag.get("type") or "").lower()
            if input_type in {"submit", "button", "image", "file"}:
                continue
            if input_type in {"checkbox", "radio"} and not input_tag.has_attr("checked"):
                continue
            payload[name] = input_tag.get("value", "")
        return action_url, payload

    def _build_cookie_header(self, client: httpx.AsyncClient) -> str:
        cookies = dict(client.cookies.items())
        if not cookies:
            return ""

        ordered_names: list[str] = []
        if self.preferred_cookie_name and self.preferred_cookie_name in cookies:
            ordered_names.append(self.preferred_cookie_name)
        ordered_names.extend(name for name in cookies if name not in ordered_names)
        return "; ".join(f"{name}={cookies[name]}" for name in ordered_names)

    async def _login(self) -> str:
        login_url = self._resolve_login_url()
        if not login_url:
            logger.warning("Forum login URL is empty; cannot auto-refresh forum cookie")
            return ""

        headers = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers, follow_redirects=True) as client:
                login_page = await client.get(login_url)
                login_page.raise_for_status()

                action_url, payload = self._extract_form_payload(login_page.text, str(login_page.url))
                if not action_url:
                    logger.warning("Could not find forum login form on %s", login_url)
                    return ""

                payload["login"] = self.username
                payload["password"] = self.password
                payload.setdefault("remember", "1")
                payload.setdefault("_xfRedirect", self.forum_root_url)

                submit_headers = {"Referer": str(login_page.url)}
                submit_resp = await client.post(action_url, data=payload, headers=submit_headers)
                submit_resp.raise_for_status()

                cookie_header = self._build_cookie_header(client)
                if not cookie_header:
                    logger.warning("Forum login succeeded but no cookies were captured")
                return cookie_header
        except Exception as exc:
            logger.warning("Forum auto-login failed: %s", exc)
            return ""

    async def ensure_cookie(self, force_refresh: bool = False) -> str:
        if not self.has_credentials:
            return self.fallback_cookie

        async with self._cookie_lock:
            if self._cached_cookie and not force_refresh:
                return self._cached_cookie

            fresh_cookie = await self._login()
            if fresh_cookie:
                self._cached_cookie = fresh_cookie
                return fresh_cookie

            return self._cached_cookie or self.fallback_cookie

    @staticmethod
    def is_login_redirect_url(url: str) -> bool:
        path = urlparse(url).path.lower()
        return "/login" in path and "/attachments/" not in path
