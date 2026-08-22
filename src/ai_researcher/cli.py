"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import Settings, load_sources
from .db import Database
from .enrich import OllamaClient
from .pipeline import Pipeline, sync_sources
from .trends import backfill_topics, build_clusters, generate_brief
from .web import queries as Q


def _log(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)-24s %(message)s",
        datefmt="%H:%M:%S",
    )


def _ctx() -> tuple[Settings, Database]:
    settings = Settings.load()
    return settings, Database(settings.db_path)


# ── commands ─────────────────────────────────────────────────────────
def cmd_run(args) -> int:
    settings, db = _ctx()
    pipeline = Pipeline(settings, db)
    only = args.source or None
    result = asyncio.run(
        pipeline.run(only=only, skip_ingest=args.no_ingest, force_brief=args.force_brief)
    )

    if result.get("status") == "busy":
        print(f"\n  {result.get('error', 'another run is active')}")
        print("  nothing was changed; try again once it finishes.\n")
        return 0

    ingest = result.get("ingest") or {}
    print()
    print(f"  run #{result.get('run_id')}  {result.get('status')}  "
          f"{result.get('elapsed_s')}s")
    if ingest:
        print(f"  sources : {ingest.get('ok', 0)} ok, "
              f"{ingest.get('failed', 0)} failed, {ingest.get('skipped', 0)} skipped")
        print(f"  items   : {ingest.get('new_items', 0)} new")
    enrich = result.get("enrich") or {}
    if enrich:
        print(f"  enriched: {enrich.get('enriched', 0)} "
              f"({enrich.get('llm', 0)} by model, {enrich.get('heuristic', 0)} heuristic), "
              f"{enrich.get('pending', 0)} pending")
    embed = result.get("embed") or {}
    if embed.get("embedded") or embed.get("total"):
        note = f", {embed['failed_batches']} batches failed" if embed.get("failed_batches") else ""
        print(f"  embedded: {embed.get('embedded', 0)} new "
              f"({embed.get('total', 0)} total{note})")
    cluster = result.get("cluster") or {}
    if cluster:
        print(f"  stories : {cluster.get('clusters', 0)} from "
              f"{cluster.get('items', 0)} items via {cluster.get('method')}")
    ollama = result.get("ollama") or {}
    if ollama:
        print(f"  ollama  : {'ready' if ollama.get('available') else 'unavailable'} "
              f"chat={ollama.get('chat_model') or '-'} "
              f"embed={ollama.get('embed_model') or '-'}")
    for err in (ingest.get("errors") or [])[:12]:
        print(f"    ! {err}")
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
        return 1
    return 0


def _lan_address() -> str:
    """The address other machines should use to reach this host.

    Resolving the hostname is the obvious approach and the wrong one: on
    Debian-family systems /etc/hosts maps the hostname to a loopback address,
    so it confidently prints a URL that works nowhere but here. Opening a UDP
    socket toward a routable address sends no packets but makes the kernel
    pick the real outbound interface, which is the one we want to advertise.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1, never actually routed to
        addr = sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()
    return "" if addr.startswith("127.") else addr


def cmd_serve(args) -> int:
    import uvicorn
    settings = Settings.load()
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"  dashboard : http://{host}:{port}")
    if host in ("0.0.0.0", "::"):
        lan = _lan_address()
        if lan:
            print(f"  on LAN    : http://{lan}:{port}")
    if settings.access_token:
        print(f"  token     : append ?k={settings.access_token}")
    uvicorn.run(
        "ai_researcher.web.app:create_app",
        host=host, port=port, factory=True,
        reload=args.reload, log_level=args.log.lower(),
    )
    return 0


def cmd_sources(args) -> int:
    settings, db = _ctx()
    sync_sources(db, load_sources(settings))
    rows = Q.source_health(db)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    width = max((len(r["name"]) for r in rows), default=20)
    print(f"\n  {'SOURCE'.ljust(width)}  {'KIND':<16} {'STATUS':<13} "
          f"{'LAST':<10} {'7d':>5}  NOTE")
    print("  " + "─" * (width + 60))
    for r in rows:
        note = r["error"][:56] if r["error"] else ""
        mark = {"ok": "✓", "not-modified": "·", "disabled": "○"}.get(r["status"], "✗")
        print(f"  {r['name'].ljust(width)}  {r['kind']:<16} "
              f"{mark} {r['status']:<11} {r['last_fetch']:<10} "
              f"{r['week_items']:>5}  {note}")
    failing = [r for r in rows if r["status"] == "error"]
    print(f"\n  {len(rows)} sources, {len(failing)} failing\n")
    return 0


def cmd_stats(args) -> int:
    _, db = _ctx()
    print(json.dumps(Q.dashboard_stats(db), indent=2))
    return 0


def cmd_brief(args) -> int:
    settings, db = _ctx()

    async def go():
        client = OllamaClient(settings)
        try:
            if args.rebuild:
                build_clusters(db)
            return await generate_brief(db, client, day=args.day, force=True)
        finally:
            await client.aclose()

    asyncio.run(go())
    brief = Q.get_brief(db, args.day)
    if brief:
        print(f"\n─── {brief['day']} "
              f"({brief['model'] or 'no model'}) ───\n")
        print(brief["markdown"])
        print()
    return 0


def cmd_doctor(args) -> int:
    """Check the things that silently degrade the dashboard."""
    settings, db = _ctx()
    print("\n  ── environment ──")
    print(f"  data dir       : {settings.data_dir}")
    print(f"  database       : {settings.db_path} "
          f"({settings.db_path.stat().st_size // 1024 if settings.db_path.exists() else 0} KB)")
    print(f"  FTS5 search    : {'yes' if db.fts_enabled else 'no (LIKE fallback)'}")

    print("\n  ── ollama ──")

    async def probe():
        client = OllamaClient(settings)
        try:
            ok = await client.probe()
            return ok, client.installed, client.chat_model, client.embed_model, client.last_error
        finally:
            await client.aclose()

    ok, installed, chat, embed, err = asyncio.run(probe())
    print(f"  host           : {settings.ollama_host}")
    print(f"  reachable      : {'yes' if ok else 'NO — ' + err}")
    print(f"  installed      : {', '.join(installed) or 'none'}")
    print(f"  chat model     : {chat or 'NONE — summaries will be extractive'}")
    if not embed:
        print("  embed model    : NONE — clustering falls back to TF-IDF")
        print("                   fix: ollama pull nomic-embed-text")
    else:
        print(f"  embed model    : {embed}")

    print("\n  ── credentials ──")
    print(f"  GITHUB_TOKEN   : {'set' if settings.github_token else 'NOT SET — 60 req/hr limit'}")
    print(f"  X_BEARER_TOKEN : {'set' if settings.x_bearer_token else 'not set — X connector off'}")
    print(f"  REDDIT oauth   : {'set' if settings.reddit_client_id else 'not set — public Atom feeds'}")

    stats = Q.dashboard_stats(db)
    print("\n  ── content ──")
    print(f"  items total    : {stats['items_total']}")
    print(f"  items last 24h : {stats['items_24h']}")
    print(f"  stories today  : {stats['stories_today']}")
    print(f"  pending enrich : {stats['pending_enrich']}")
    print(f"  sources ok     : {stats['sources_ok']}/{stats['sources_total']}"
          f"  ({stats['sources_failing']} failing)")
    print(f"  last run       : {stats['last_run']} ({stats['last_run_status']})")
    print()
    return 0


def cmd_recluster(args) -> int:
    settings, db = _ctx()
    print(json.dumps(build_clusters(db, window_hours=args.hours), indent=2))
    backfill_topics(db, days=args.backfill)
    print(f"  topics backfilled for {args.backfill} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-researcher", description="Local AI trends dashboard"
    )
    parser.add_argument("--log", default="INFO", help="log level")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="fetch, enrich, cluster, and brief")
    p.add_argument("--source", action="append", help="limit to source key(s)")
    p.add_argument("--no-ingest", action="store_true", help="re-analyse without fetching")
    p.add_argument("--force-brief", action="store_true", help="regenerate today's brief")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("serve", help="run the web dashboard")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("sources", help="show per-source health")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser("doctor", help="diagnose degraded capabilities")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("brief", help="print (and regenerate) the daily brief")
    p.add_argument("--day")
    p.add_argument("--rebuild", action="store_true", help="recluster first")
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("stats", help="dashboard counters as JSON")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("recluster", help="rebuild stories and topic history")
    p.add_argument("--hours", type=int, default=48)
    p.add_argument("--backfill", type=int, default=14)
    p.set_defaults(fn=cmd_recluster)

    args = parser.parse_args(argv)
    _log(args.log)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
