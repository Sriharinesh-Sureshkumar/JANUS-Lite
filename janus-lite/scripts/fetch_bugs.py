#!/usr/bin/env python3
"""Fetch the pod's `bugs` table via the Lemma CLI and write it to a static
JSON file the public dashboard can fetch without authentication.

The dashboard is a public Lemma App, but `client.datastore.query()` still
hits an authenticated endpoint even for public apps (confirmed: no public/
anonymous read path exists in lemma-sdk or the Lemma docs). So instead of
querying live from the browser, this script runs the same read-only SQL
through an authenticated CLI session on the server side and bakes the
result into the app bundle at deploy time.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

POD = "janus-lite"
SQL = "SELECT * FROM bugs ORDER BY created_at DESC"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "site" / "data" / "bugs.json"


def fetch_bugs():
    result = subprocess.run(
        ["lemma", "--json", "query", "run", SQL, "--pod", POD],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"lemma query run failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout)
    return payload.get("items", [])


def main():
    bugs = fetch_bugs()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "items": bugs},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(bugs)} bugs to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI entry point
        print(f"fetch_bugs failed: {exc}", file=sys.stderr)
        sys.exit(1)
