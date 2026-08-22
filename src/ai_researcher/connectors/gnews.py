"""Google News RSS connector.

Several AI vendors publish no feed at all — Anthropic, Meta AI, Cohere, Groq,
ElevenLabs, Runway and LlamaIndex among them. A Google News `site:` search
returns their posts as a normal RSS feed, which recovers coverage that would
otherwise be missing entirely.

Two quirks are handled here:

* Item links are opaque `news.google.com/rss/articles/CBMi…` wrappers whose real
  destination is only resolvable by a JS-executing client. The wrapper works in
  a browser, so it is kept as the click target, and the true publisher is read
  from the feed's `<source>` element for display and attribution instead.
* Titles carry a " - Publisher" suffix. That is stripped, because the content
  hash is computed from the title and the suffix would stop a Google News copy
  of an article from deduplicating against the same article seen elsewhere.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

import feedparser

from ..config import Source
from ..util import domain_of, parse_datetime
from .base import Connector, FetchResult, RawItem

ENDPOINT = "https://news.google.com/rss/search"

# " - Anthropic" / " — The Verge" at the very end of a headline.
_PUBLISHER_SUFFIX = re.compile(r"\s+[-–—]\s+[^-–—]{2,40}$")

# A `site:` query indexes the whole domain, so it drags in careers pages, API
# reference stubs and legal boilerplate alongside the blog. Left unfiltered
# these dominate: one vendor contributed 57 items, of which ~50 were job
# postings and docs pages, and they clustered together into a fake "story".
_JUNK_TITLE = re.compile(
    r"""(?ix)
    ^(open\s+positions|careers?|jobs?|pricing|about|contact|login|sign\s*in)\b
  | \b(engineer|manager|marketer|recruiter|designer|analyst|specialist|
        intern|internship|director|lead)\s*[-–—,]\s*(north|south|emea|apac|
        remote|us|uk|europe|america)
  | \b(full[- ]time|part[- ]time|we'?re\s+hiring|join\s+our\s+team)\b
  | ^(privacy|terms|cookie|legal|security|trust|status|changelog|docs?|
      documentation|api\s+reference)\b
  | ^(list|create|get|delete|update|patch|post|put)\s+[a-z]+(\s+[a-z]+)?$
  | ^[\s\-–—]*$
    """
)
# Titles worth keeping are sentences, not labels. Two words is the floor.
MIN_TITLE_WORDS = 3


class GoogleNewsConnector(Connector):
    kind = "gnews"

    def available(self, source: Source) -> tuple[bool, str]:
        if not source.config.get("query"):
            return False, "no query configured"
        return True, ""

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        query = source.config["query"]
        days = int(source.config.get("days", 14))
        locale = source.config.get("locale", "en-US")
        country = source.config.get("country", "US")

        url = (
            f"{ENDPOINT}?q={quote_plus(f'{query} when:{days}d')}"
            f"&hl={locale}&gl={country}&ceid={country}:{locale.split('-')[0]}"
        )
        resp = await self.fetcher.get(url)
        if resp is None:
            return FetchResult(status="error", error="request failed")
        if resp.status_code >= 400:
            return FetchResult(status="error", error=f"HTTP {resp.status_code}")

        parsed = feedparser.parse(resp.content)
        entries = parsed.get("entries") or []
        if not entries:
            # An over-narrow query legitimately returns nothing; say so plainly
            # rather than looking like a broken feed.
            return FetchResult(status="ok", error="no results for query")

        allow = {d.lower().lstrip(".") for d in (source.config.get("only_domains") or [])}
        min_words = int(source.config.get("min_title_words", MIN_TITLE_WORDS))

        items: list[RawItem] = []
        dropped = 0
        for entry in entries:
            src = entry.get("source") or {}
            publisher = (src.get("title") or "").strip()
            publisher_url = (src.get("href") or "").strip()
            publisher_domain = domain_of(publisher_url)

            # A `site:` query can still surface syndicated copies; this keeps a
            # vendor feed to that vendor when the caller asks for it.
            if allow and publisher_domain and publisher_domain not in allow:
                continue

            title = (entry.get("title") or "").strip()
            if publisher and title.endswith(publisher):
                title = title[: -len(publisher)].rstrip(" -–—")
            else:
                title = _PUBLISHER_SUFFIX.sub("", title)
            if not title:
                continue
            # Drop careers/docs/legal pages the domain search dragged in.
            if _JUNK_TITLE.search(title) or len(title.split()) < min_words:
                dropped += 1
                continue

            link = entry.get("link") or ""
            items.append(
                RawItem(
                    external_id=str(entry.get("id") or link)[:400],
                    title=title,
                    url=link,
                    body=entry.get("summary", "") or "",
                    author=publisher,
                    published_at=parse_datetime(entry.get("published")),
                    meta={
                        "via": "gnews",
                        "publisher": publisher,
                        "publisher_url": publisher_url,
                        "publisher_domain": publisher_domain,
                        # The click target is a redirect, so the UI should show
                        # the publisher's domain rather than news.google.com.
                        "display_domain": publisher_domain,
                        "query": query,
                    },
                ).normalized()
            )
        note = f"filtered {dropped} non-article pages" if dropped else ""
        return FetchResult(items=items, error=note)
