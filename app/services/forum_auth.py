import asyncio
import logging
import re
import time
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
        self._login_retry_not_before: float = 0.0
        self._login_retry_reason: str = ""

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

    @staticmethod
    def _cookie_names(client: httpx.AsyncClient) -> str:
        names = sorted({name for name, _ in client.cookies.items()})
        return ",".join(names) if names else "<none>"

    @staticmethod
    def _has_login_form(html: str) -> bool:
        if not html:
            return False
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one("form[action*='login/login']"):
            return True
        for candidate in soup.select("form"):
            if candidate.select_one("input[name='login']") and candidate.select_one("input[name='password']"):
                return True
        return False

    @staticmethod
    def _looks_authenticated(html: str) -> bool:
        if not html:
            return False
        lowered = html.lower()
        if 'data-logged-in="true"' in lowered or "data-logged-in='true'" in lowered:
            return True
        if "/logout/" in lowered:
            return True
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one("a[href*='/logout/'], form[action*='/logout/']"):
            return True
        return False

    @staticmethod
    def _extract_login_retry_after_seconds(html: str) -> int | None:
        if not html:
            return None
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        patterns = [
            r"подождать\s+не\s+менее\s+(\d+)\s+сек",
            r"подождать\s+(\d+)\s+сек",
            r"wait\s+at\s+least\s+(\d+)\s+seconds?",
            r"please\s+wait\s+(\d+)\s+seconds?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return max(1, int(match.group(1)))
            except Exception:
                continue
        return None

    def _set_login_retry_cooldown(self, seconds: int, reason: str) -> None:
        safe_seconds = max(1, min(int(seconds), 600))
        self._login_retry_not_before = time.monotonic() + safe_seconds
        self._login_retry_reason = reason

    def _remaining_login_retry_seconds(self) -> int:
        remaining = self._login_retry_not_before - time.monotonic()
        if remaining <= 0:
            return 0
        return int(remaining) + 1

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

                cookies = dict(client.cookies.items())
                has_user_cookie = "xf_user" in cookies
                has_auth_marker = self._looks_authenticated(submit_resp.text)
                has_login_form = self._has_login_form(submit_resp.text)
                final_url = str(submit_resp.url)
                redirected_to_login = self.is_login_redirect_url(final_url)
                if redirected_to_login or has_login_form or not (has_user_cookie or has_auth_marker):
                    retry_after = self._extract_login_retry_after_seconds(submit_resp.text)
                    if retry_after:
                        self._set_login_retry_cooldown(retry_after + 1, "forum_rate_limit")
                    else:
                        self._set_login_retry_cooldown(10, "unauthenticated_login_response")
                    logger.warning(
                        "Forum login did not establish an authenticated session "
                        "(final_url=%s, redirected_to_login=%s, has_login_form=%s, "
                        "has_xf_user=%s, has_auth_marker=%s, cookie_names=%s, retry_after=%s)",
                        final_url,
                        redirected_to_login,
                        has_login_form,
                        has_user_cookie,
                        has_auth_marker,
                        self._cookie_names(client),
                        retry_after,
                    )
                    return ""

                cookie_header = self._build_cookie_header(client)
                if not cookie_header:
                    logger.warning("Forum login succeeded but no cookies were captured")
                self._login_retry_not_before = 0.0
                self._login_retry_reason = ""
                return cookie_header
        except Exception as exc:
            self._set_login_retry_cooldown(10, "login_exception")
            logger.warning("Forum auto-login failed: %s", exc)
            return ""

    async def ensure_cookie(self, force_refresh: bool = False) -> str:
        if not self.has_credentials:
            return self.fallback_cookie

        async with self._cookie_lock:
            cooldown = self._remaining_login_retry_seconds()
            if cooldown > 0:
                logger.debug(
                    "Skipping forum auto-login due to cooldown (%ss remaining, reason=%s)",
                    cooldown,
                    self._login_retry_reason or "unknown",
                )
                return self._cached_cookie or self.fallback_cookie

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
