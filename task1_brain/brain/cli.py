"""python -m brain.cli serve | crawl | sync | ask "..." | demo"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from .app import Brain


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="brain")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl"); c.add_argument("--limit", type=int); c.add_argument("--retry-failed", action="store_true")
    sub.add_parser("sync")
    a = sub.add_parser("ask"); a.add_argument("question")
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8001)
    sub.add_parser("demo")
    args = ap.parse_args()

    if args.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(), host="0.0.0.0", port=args.port)
        return
    if args.cmd == "demo":
        from .demo import seed
        asyncio.run(seed()); return

    async def run() -> None:
        b = Brain.create()
        if args.cmd == "crawl":
            from .crawl import first_crawl, process_queue
            rep = await (process_queue(b, args.limit, True) if args.retry_failed else first_crawl(b, args.limit))
            print(rep)
        elif args.cmd == "sync":
            from .sync import run_sync
            print(json.dumps(await run_sync(b), indent=2))
        elif args.cmd == "ask":
            from .qa import ask
            import dataclasses
            print(json.dumps(dataclasses.asdict(await ask(b, args.question)), indent=2))
        if hasattr(b.fetcher, "aclose"):
            await b.fetcher.aclose()
    asyncio.run(run())


if __name__ == "__main__":
    main()
