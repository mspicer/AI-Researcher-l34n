"""Shared async HTTP client: retries, backoff, and per-host politeness."""

from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict
from typing import Any

import httpx

from .util import domain_of

log = logging.getLogger("ai_researcher.http")

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class Fetcher:
    """One client for the whole run, with a global and per-host concurrency cap.

    Feeds live on shared hosts (Substack, GitHub, Reddit), so an unbounded fan-out
    earns rate limits fast. Two semaphores keep us a well-behaved client.
    """

    def __init__(self, user_agent: str, concurrency: int = 8, per_host: int = 3):
        self._client = httpx.AsyncClient(
            headers={
                # Several publishers (Substack, WordPress-behind-Cloudflare)
                # 403 anything that looks like a bot, so the configured agent is
                # sent alongside a browser-shaped header set.
                "User-Agent": user_agent,
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Accept": "application/atom+xml, application/rss+xml, application/xml, "
                          "application/json;q=0.9, text/html;q=0.8, */*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=httpx.Timeout(30.0, connect=12.0),
            follow_redirects=True,
            http2=False,
        )
        self._gate = asyncio.Semaphore(max(1, concurrency))
        self._host_gates: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(max(1, per_host))
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> httpx.Response | None:
        """GET with backoff. Returns None when every attempt failed."""
        host = domain_of(url) or url
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._gate, self._host_gates[host]:
                    resp = await self._client.get(url, headers=headers, params=params)
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                last_exc = exc
                log.debug("GET %s failed (%s/%s): %s", url, attempt + 1, attempts, exc)
            else:
                if resp.status_code in RETRY_STATUS and attempt < attempts - 1:
                    delay = self._retry_delay(resp, attempt)
                    log.debug("GET %s -> %s, retrying in %.1fs", url, resp.status_code, delay)
                    await asyncio.sleep(delay)
                    continue
                return resp
            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (2**attempt) + random.uniform(0, 0.5))
        if last_exc:
            log.info("GET %s gave up: %s", url, last_exc)
        return None

    async def get_json(self, url: str, **kwargs) -> Any | None:
        resp = await self.get(url, **kwargs)
        if resp is None or resp.status_code >= 400:
            return None
        try:
            return resp.json()
        except ValueError:
            log.debug("GET %s returned non-JSON body", url)
            return None

    async def post_json(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> Any | None:
        """Single-attempt POST. Used for OAuth token exchange, not for polling."""
        host = domain_of(url) or url
        try:
            async with self._gate, self._host_gates[host]:
                resp = await self._client.post(
                    url, data=data, json=json_body, headers=headers, auth=auth
                )
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            log.info("POST %s failed: %s", url, exc)
            return None
        if resp.status_code >= 400:
            log.info("POST %s -> HTTP %s", url, resp.status_code)
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 30.0)
            except ValueError:
                pass
        return min(1.5 * (2**attempt) + random.uniform(0, 0.75), 30.0)
