from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, destination):
        return None


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class Outbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0, sent_at REAL)"
        )
        self.db.commit()

    def enqueue(self, project, kind, result, events=None, key=None):
        if not isinstance(result, dict) or not isinstance(events or [], list):
            raise ValueError("result must be an object and events an array")
        body = {
            "project": project,
            "kind": kind,
            "result": result,
            "events": events or [],
        }
        key = key or hashlib.sha256(canonical(body).encode()).hexdigest()
        body["clientKey"] = key
        payload = canonical(body)
        if len(payload.encode()) > 262144:
            raise ValueError("report exceeds 256 KiB")
        with self.db:
            prior = self.db.execute(
                "SELECT payload FROM outbox WHERE key=?", (key,)
            ).fetchone()
            if prior and prior[0] != payload:
                raise ValueError("local idempotency conflict")
            if (
                not prior
                and self.db.execute(
                    "SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL"
                ).fetchone()[0]
                >= 10000
            ):
                raise OverflowError("outbox full")
            self.db.execute(
                "INSERT OR IGNORE INTO outbox(key,payload) VALUES (?,?)", (key, payload)
            )
        return key

    def drain(self, endpoint, token, limit=100, transport=None):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("HTTPS endpoint required")
        if not token:
            raise ValueError("BRUNNODEV_ACCESS_TOKEN is required")
        transport = transport or self._send
        sent, failed = 0, 0
        rows = self.db.execute(
            "SELECT key,payload,attempts FROM outbox WHERE sent_at IS NULL AND next_at<=? ORDER BY rowid LIMIT ?",
            (time.time(), min(max(limit, 1), 500)),
        ).fetchall()
        for key, payload, attempts in rows:
            try:
                status = transport(endpoint, token, payload)
            except (urllib.error.URLError, TimeoutError, OSError):
                status = 503
            with self.db:
                if 200 <= status < 300:
                    self.db.execute(
                        "UPDATE outbox SET sent_at=? WHERE key=?", (time.time(), key)
                    )
                    sent += 1
                else:
                    delay = min(3600, 2 ** min(attempts + 1, 11)) + random.random()
                    self.db.execute(
                        "UPDATE outbox SET attempts=attempts+1,next_at=? WHERE key=?",
                        (time.time() + delay, key),
                    )
                    failed += 1
            if status in (401, 403):
                break
        return {
            "sent": sent,
            "failed": failed,
            "pending": self.db.execute(
                "SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL"
            ).fetchone()[0],
        }

    @staticmethod
    def _send(endpoint, token, payload):
        request = urllib.request.Request(
            endpoint,
            data=payload.encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                request, timeout=15
            ) as response:
                data = json.loads(response.read(4096))
                return response.status if data.get("persisted") is True else 502
        except urllib.error.HTTPError as error:
            return error.code
        except (ValueError, UnicodeDecodeError):
            return 502

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Persist native reports to the Brunno Dev operations API"
    )
    parser.add_argument("command", choices=("enqueue", "sync"))
    parser.add_argument("file", nargs="?", default="-")
    parser.add_argument(
        "--project", default=Path(__file__).resolve().parent.parent.name
    )
    parser.add_argument("--kind", default="report")
    parser.add_argument("--key")
    parser.add_argument("--outbox", default=".local/outbox.sqlite3")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get(
            "BRUNNODEV_API_URL", "https://vercel-home-telemetry-api.vercel.app/api/runs"
        ),
    )
    args = parser.parse_args()
    outbox = Outbox(args.outbox)
    try:
        if args.command == "enqueue":
            data = (
                json.load(sys.stdin)
                if args.file == "-"
                else json.loads(Path(args.file).read_text())
            )
            print(
                canonical(
                    {
                        "queued": outbox.enqueue(
                            args.project, args.kind, data, key=args.key
                        )
                    }
                )
            )
        else:
            print(
                canonical(
                    outbox.drain(
                        args.endpoint, os.environ.get("BRUNNODEV_ACCESS_TOKEN")
                    )
                )
            )
    finally:
        outbox.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, OverflowError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
