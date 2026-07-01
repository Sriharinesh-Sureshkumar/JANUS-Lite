#!/usr/bin/env python3
"""
process_bug_report.py

Usage:
    python process_bug_report.py "Raw bug report text here"

Runs `lemma chat triager`, extracts the JSON block from the output,
and persists it to the bugs table via `lemma records create`.
"""

import io
import json
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def run(cmd, **kwargs):
    """Run a command and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", **kwargs
    )
    return result.stdout, result.stderr, result.returncode


def fix_newlines_in_strings(text):
    """Replace bare newlines inside JSON string values with spaces.

    lemma's terminal output word-wraps long values, embedding literal \\n
    inside string fields which makes json.loads reject the block.
    """
    result = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == "\\" and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif ch == "\n" and in_string:
            result.append(" ")
        else:
            result.append(ch)
    return "".join(result)


def extract_json_block(text):
    """Return the first ```json ... ``` block found in text, parsed."""
    text = text.replace("\x00", "")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return None
    cleaned = fix_newlines_in_strings(match.group(1))
    return json.loads(cleaned)


def main():
    if len(sys.argv) < 2:
        print("Usage: python process_bug_report.py \"<bug report>\"")
        sys.exit(1)

    report = sys.argv[1]

    # ── Step 1: call triager ────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Sending report to triager agent...")
    print("=" * 60)

    stdout, stderr, rc = run(["lemma", "--timeout", "120", "chat", "triager", "-m", report])

    # lemma writes its chat UI to stdout; stderr may carry daemon noise
    raw_output = stdout + stderr
    print(raw_output)

    if rc != 0:
        print(f"\n[FAIL] lemma chat triager exited {rc}")
        sys.exit(rc)

    # ── Step 2: extract JSON ────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 2: Extracting JSON block...")
    print("=" * 60)

    payload = extract_json_block(raw_output)
    if payload is None:
        print("[FAIL] No ```json block found in triager output.")
        print("Raw output was:")
        print(raw_output)
        sys.exit(1)

    payload_str = json.dumps(payload, indent=2)
    print(payload_str)

    # ── Step 3: write to bugs table ─────────────────────────────────────────
    print("=" * 60)
    print("STEP 3: Writing record to bugs table...")
    print("=" * 60)

    compact = json.dumps(payload)
    stdout2, stderr2, rc2 = run(["lemma", "records", "create", "bugs", "-d", compact])

    print(stdout2)
    if stderr2:
        print(stderr2)

    if rc2 != 0:
        print(f"\n[FAIL] lemma records create exited {rc2}")
        sys.exit(rc2)

    print("\n[OK] Bug record created successfully.")


if __name__ == "__main__":
    main()
