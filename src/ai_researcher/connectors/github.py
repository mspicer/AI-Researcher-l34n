"""GitHub connectors: releases for tracked repos, and newly-hot repos by topic.

GitHub's "trending" page has no API, so the trending connector approximates it
with a search for recently-created repos that already have real traction — which
is what you actually want to notice: the project that appeared this week.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from ..config import Source
from ..util import parse_datetime, truncate, utcnow
from .base import Connector, FetchResult, RawItem

API = "https://api.github.com"


class _GitHubBase(Connector):
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers


class GitHubReleasesConnector(_GitHubBase):
    kind = "github_releases"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        repos = source.config.get("repos") or []
        if not repos:
            return FetchResult(status="error", error="no repos configured")
        cutoff = utcnow() - timedelta(days=max(self.settings.item_max_age_days, 21))

        results = await asyncio.gather(
            *(self._repo_releases(repo, cutoff) for repo in repos),
            return_exceptions=True,
        )

        items: list[RawItem] = []
        failures = 0
        for result in results:
            if isinstance(result, BaseException) or result is None:
                failures += 1
                continue
            items.extend(result)

        if not items and failures == len(repos):
            return FetchResult(status="error", error="all repo requests failed")
        status = "ok" if failures == 0 else "ok"
        return FetchResult(items=items, status=status,
                           error=f"{failures} repos failed" if failures else "")

    async def _repo_releases(self, repo: str, cutoff) -> list[RawItem] | None:
        payload = await self.fetcher.get_json(
            f"{API}/repos/{repo}/releases",
            headers=self._headers(),
            params={"per_page": 10},
        )
        if payload is None:
            return None

        out: list[RawItem] = []
        for release in payload:
            if release.get("draft"):
                continue
            # Projects like llama.cpp tag a build nearly every day. Every one is
            # a real release, but seven rows of "b10545, b10546, b10547" crowd
            # out actual news, so only the newest per repo is surfaced and the
            # rest are left to the changelog.
            if out:
                break
            published = parse_datetime(release.get("published_at") or release.get("created_at"))
            if published and published < cutoff:
                continue
            tag = release.get("tag_name") or ""
            name = release.get("name") or tag
            out.append(
                RawItem(
                    external_id=f"ghrel:{repo}:{tag}",
                    title=f"{repo} {tag} released" + (f" — {name}" if name and name != tag else ""),
                    url=release.get("html_url") or f"https://github.com/{repo}/releases",
                    body=truncate(release.get("body") or "", 3000),
                    author=repo.split("/")[0],
                    published_at=published,
                    meta={
                        "repo": repo,
                        "tag": tag,
                        "prerelease": bool(release.get("prerelease")),
                        "is_release": True,
                    },
                ).normalized()
            )
        return out


class GitHubTrendingConnector(_GitHubBase):
    kind = "github_trending"

    async def fetch(self, source: Source, state: dict[str, Any]) -> FetchResult:
        topics = source.config.get("topics") or ["llm"]
        days = int(source.config.get("days", 7))
        min_stars = int(source.config.get("min_stars", 100))
        since = (utcnow() - timedelta(days=days)).date().isoformat()

        results = await asyncio.gather(
            *(self._search(topic, since, min_stars) for topic in topics),
            return_exceptions=True,
        )

        items: dict[str, RawItem] = {}
        failures = 0
        for result in results:
            if isinstance(result, BaseException) or result is None:
                failures += 1
                continue
            for item in result:
                existing = items.get(item.external_id)
                if existing is None:
                    items[item.external_id] = item
                else:
                    # Same repo matched several topics — record all of them.
                    existing.meta.setdefault("topics", []).extend(item.meta.get("topics", []))

        if not items and failures:
            return FetchResult(status="error", error=f"{failures} topic searches failed")
        return FetchResult(items=list(items.values()))

    async def _search(self, topic: str, since: str, min_stars: int) -> list[RawItem] | None:
        payload = await self.fetcher.get_json(
            f"{API}/search/repositories",
            headers=self._headers(),
            params={
                "q": f"topic:{topic} created:>{since} stars:>={min_stars}",
                "sort": "stars",
                "order": "desc",
                "per_page": 15,
            },
        )
        if not payload:
            return None

        out: list[RawItem] = []
        for repo in payload.get("items") or []:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            stars = int(repo.get("stargazers_count") or 0)
            out.append(
                RawItem(
                    external_id=f"ghrepo:{full_name}",
                    title=f"{full_name} — {stars:,}★ in its first weeks",
                    url=repo.get("html_url") or "",
                    body=repo.get("description") or "",
                    author=(repo.get("owner") or {}).get("login", ""),
                    published_at=parse_datetime(repo.get("created_at")),
                    engagement=float(stars),
                    meta={
                        "repo": full_name,
                        "stars": stars,
                        "language": repo.get("language") or "",
                        "topics": [topic],
                        "is_new_project": True,
                    },
                ).normalized()
            )
        return out
