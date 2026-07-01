#!/usr/bin/env python3
"""
process_verification.py

Usage:
    python process_verification.py <bug_id> <hypothesis> <priority> [<repo_url>]

Runs `lemma chat verifier-fixer` with a triaged bug's details, extracts the
JSON block from the output, and persists it back to the bugs row via
`lemma records update bugs <bug_id> -d '<json>'`.

If the result is verified_and_fixed, automatically opens a GitHub PR and
writes the PR URL back to the bugs table.

Arguments:
    bug_id      — the bugs table primary key (UUID)
    hypothesis  — the triager's hypothesis string
    priority    — critical / high / medium / low
    repo_url    — optional; omit or pass "null" if not yet known
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Force UTF-8 output so lemma's box-drawing characters don't crash on CP1252 terminals.
# Guard against double-wrapping when the module is imported by another script that
# already replaced sys.stdout (re-wrapping closes the first wrapper's buffer).
def _ensure_utf8(stream):
    enc = getattr(stream, "encoding", None) or ""
    if enc.lower().replace("-", "").startswith("utf8") or enc.lower() == "utf-8-sig":
        return stream
    return io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")

sys.stdout = _ensure_utf8(sys.stdout)
sys.stderr = _ensure_utf8(sys.stderr)


def run(cmd, **kwargs):
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
    """Return the last ```json ... ``` block found in text, parsed.

    Uses the last block because verifier-fixer may emit intermediate
    JSON-like output during reasoning before its final structured block.
    """
    text = text.replace("\x00", "")
    matches = list(re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL))
    if not matches:
        return None
    cleaned = fix_newlines_in_strings(matches[-1].group(1))
    return json.loads(cleaned)


# ── Keyword locator ──────────────────────────────────────────────────────────

_STOPWORDS = {
    "and", "the", "for", "with", "from", "this", "that", "which", "when",
    "where", "what", "have", "been", "not", "are", "use", "used", "using",
    "may", "can", "will", "does", "into", "path", "than", "instead",
    "causing", "while", "also", "more", "some", "open", "read", "write",
    "find", "set", "get", "run", "add", "new", "all", "any", "each",
}
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules"}
_CODE_EXTS = {".py", ".js", ".ts", ".go", ".java", ".rb", ".rs", ".c", ".cpp",
              ".h", ".jsx", ".tsx", ".md"}


def extract_keywords(hypothesis):
    """Pull code identifiers out of a natural-language hypothesis string."""
    candidates = []

    # Quoted identifiers: 'foo_bar' or "FooBar"
    for m in re.finditer(r"['\"]([a-zA-Z_][a-zA-Z0-9_]{2,})['\"]", hypothesis):
        candidates.append(m.group(1))

    # Square-bracket accesses: c[case_id], obj[key_name]
    for m in re.finditer(r"\[([a-zA-Z_][a-zA-Z0-9_]{2,})\]", hypothesis):
        candidates.append(m.group(1))

    # snake_case with at least one underscore
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", hypothesis):
        candidates.append(m.group(1))

    # camelCase / PascalCase (lowercase run followed by uppercase)
    for m in re.finditer(r"\b([a-zA-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b", hypothesis):
        candidates.append(m.group(1))

    # File names: something.py / something.js
    for m in re.finditer(r"\b(\w+\.(?:py|js|ts|go|java|rb|rs))\b", hypothesis):
        candidates.append(m.group(1))

    seen = set()
    result = []
    for kw in candidates:
        if kw.lower() not in _STOPWORDS and kw not in seen and len(kw) > 2:
            seen.add(kw)
            result.append(kw)
    return result[:10]


def _search_python(kw, repo_path, max_hits=15):
    """Pure-Python fallback search when rg/grep are absent."""
    hits = []
    pattern = re.compile(re.escape(kw), re.IGNORECASE)
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            if os.path.splitext(fname)[1] not in _CODE_EXTS:
                continue
            full = os.path.join(root, fname)
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern.search(line):
                            hits.append((
                                os.path.relpath(full, repo_path),
                                lineno,
                                line.rstrip(),
                            ))
                            if len(hits) >= max_hits:
                                return hits
            except OSError:
                continue
    return hits


def search_keywords(keywords, repo_path):
    """Search for each keyword; return {kw: [(rel_path, lineno, line_text)]}."""
    use_rg = shutil.which("rg") is not None
    use_grep = not use_rg and shutil.which("grep") is not None
    results = {}

    for kw in keywords:
        hits = []
        if use_rg:
            stdout, _, _ = run([
                "rg", "--json", kw, repo_path,
                "--glob=!.git", "--glob=!venv", "--glob=!__pycache__",
            ])
            for raw in stdout.splitlines():
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "match":
                    continue
                data = obj["data"]
                rel = os.path.relpath(data["path"]["text"], repo_path)
                hits.append((rel, data["line_number"], data["lines"]["text"].rstrip()))
                if len(hits) >= 15:
                    break
        elif use_grep:
            stdout, _, _ = run([
                "grep", "-rn", "--include=*.py", "--include=*.js",
                "--include=*.ts", kw, repo_path,
            ])
            for line in stdout.splitlines():
                # rsplit from right so Windows drive letters (C:\...) don't break the split
                parts = line.rsplit(":", 2)
                if len(parts) < 3:
                    continue
                path, lineno_s, text = parts
                try:
                    lineno = int(lineno_s)
                except ValueError:
                    continue
                rel = os.path.relpath(path, repo_path)
                if not any(p in rel.split(os.sep) for p in _SKIP_DIRS):
                    hits.append((rel, lineno, text.rstrip()))
                if len(hits) >= 15:
                    break
        else:
            hits = _search_python(kw, repo_path)

        if hits:
            results[kw] = hits

    return results


def build_location_context(keyword_hits, repo_path):
    """Format search results into a location context string with code snippets."""
    if not keyword_hits:
        return ""

    sections = []
    for kw, hits in keyword_hits.items():
        # Group by file, keep up to 5 files and 3 matches per file
        by_file = {}
        for rel, lineno, line_text in hits:
            by_file.setdefault(rel, []).append((lineno, line_text))

        header = [f"Keyword '{kw}' found in:"]
        snippets = []

        for rel, matches in list(by_file.items())[:5]:
            full = os.path.join(repo_path, rel)
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
            except OSError:
                continue

            for lineno, line_text in matches[:3]:
                header.append(f"  - {rel} line {lineno}: {line_text.strip()}")

                # 10-line context window (5 before, 5 after)
                start = max(0, lineno - 6)
                end = min(len(all_lines), lineno + 5)
                ctx = []
                for i in range(start, end):
                    marker = ">>>" if (i + 1) == lineno else "   "
                    ctx.append(f"    {marker} {i+1}: {all_lines[i].rstrip()}")
                snippets.append(f"\n  [{rel}:{lineno}]\n" + "\n".join(ctx))

        sections.append("\n".join(header) + "\n".join(snippets))

    return "\n\n".join(sections)


def locate_in_repo(repo_url, keywords, timeout=60):
    """Clone repo, search for keywords, return (context_string, tmpdir)."""
    # Use D: drive explicitly — C:\Temp may have no space left on Windows machines
    _tmp_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".janus_tmp")
    os.makedirs(_tmp_base, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="kw_", dir=_tmp_base)
    _, _, rc = run(
        ["git", "clone", "--depth=1", repo_url, tmpdir],
        timeout=timeout,
    )
    if rc != 0:
        return "", tmpdir

    hits = search_keywords(keywords, tmpdir)
    context = build_location_context(hits, tmpdir)
    return context, tmpdir


# ── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(bug_id, hypothesis, priority, repo_url, location_context=""):
    parts = [
        f"Bug id: {bug_id}",
        f"Priority: {priority}",
        f"Hypothesis: {hypothesis}",
    ]
    if repo_url and repo_url.lower() != "null":
        parts.append(f"Repo URL: {repo_url}")
    else:
        parts.append("Repo URL: not yet available — use a placeholder clone target if needed.")

    if location_context:
        parts.append(
            "\nKeyword location context (pre-searched for you — start here):\n"
            + location_context
        )

    return "\n".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 4:
        print("Usage: python process_verification.py <bug_id> <hypothesis> <priority> [<repo_url>]")
        sys.exit(1)

    bug_id = sys.argv[1]
    hypothesis = sys.argv[2]
    priority = sys.argv[3]
    repo_url = sys.argv[4] if len(sys.argv) > 4 else None

    # ── Step 0: keyword locator ─────────────────────────────────────────────
    print("=" * 60)
    print("STEP 0: Locating keywords in repo...")
    print("=" * 60)

    keywords = extract_keywords(hypothesis)
    print(f"Keywords extracted: {keywords}")

    location_context = ""
    tmpdir = None
    if repo_url and repo_url.lower() != "null" and keywords:
        print(f"Cloning {repo_url} ...")
        location_context, tmpdir = locate_in_repo(repo_url, keywords)
        if location_context:
            print("Location context:\n")
            print(location_context)
        else:
            print("[INFO] No keyword hits found (or clone failed) — proceeding without context.")
    else:
        print("[INFO] No repo URL or no keywords — skipping locator.")

    prompt = build_prompt(bug_id, hypothesis, priority, repo_url, location_context)

    # Clean up clone now that context is extracted
    if tmpdir and os.path.isdir(tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Step 1: run verifier-fixer ──────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Sending bug to verifier-fixer agent...")
    print("=" * 60)
    print(f"Prompt:\n{prompt}\n")

    stdout, stderr, rc = run(["lemma", "--timeout", "600", "chat", "verifier-fixer", "-m", prompt])
    raw_output = stdout + stderr
    print(raw_output)

    if rc != 0:
        print(f"\n[FAIL] lemma chat verifier-fixer exited {rc}")
        sys.exit(rc)

    # ── Step 2: extract JSON ────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 2: Extracting JSON block...")
    print("=" * 60)

    payload = extract_json_block(raw_output)
    if payload is None:
        print("[FAIL] No ```json block found in verifier-fixer output.")
        print("Raw output was:")
        print(raw_output)
        sys.exit(1)

    print(json.dumps(payload, indent=2))

    # ── Step 3: update the bugs row ─────────────────────────────────────────
    print("=" * 60)
    print(f"STEP 3: Updating bugs row {bug_id}...")
    print("=" * 60)

    compact = json.dumps(payload)
    stdout2, stderr2, rc2 = run(
        ["lemma", "records", "update", "bugs", bug_id, "-d", compact]
    )

    print(stdout2)
    if stderr2:
        print(stderr2)

    if rc2 != 0:
        print(f"\n[FAIL] lemma records update exited {rc2}")
        sys.exit(rc2)

    print(f"\n[OK] Bug {bug_id} updated with status: {payload.get('status', '?')}")

    # ── Step 4: open PR if verified_and_fixed ───────────────────────────────
    if payload.get("status") != "verified_and_fixed":
        return

    print("=" * 60)
    print("STEP 4: Opening GitHub PR...")
    print("=" * 60)

    hypothesis_short = hypothesis[:60].rstrip()
    evidence = payload.get("evidence_log", "")
    patch = payload.get("patch_diff", "")
    pr_body = f"JANUS-Lite verified fix\n\nEvidence:\n{evidence}\n\nPatch:\n{patch}"

    stdout3, stderr3, rc3 = run([
        "gh", "pr", "create",
        "--repo", "Sriharinesh-Sureshkumar/sahayak-janus-demo",
        "--title", f"fix: {hypothesis_short}",
        "--body", pr_body,
        "--base", "main",
        "--head", "janus-demo-target",
    ])

    if rc3 != 0:
        print(f"[WARN] gh pr create failed (rc={rc3}) — skipping PR URL write.")
        if stdout3:
            print("STDOUT:", stdout3)
        if stderr3:
            print("STDERR:", stderr3)
        return

    pr_url = stdout3.strip().splitlines()[-1].strip()
    print(f"PR opened: {pr_url}")

    # ── Step 5: write PR URL back to the bugs row ───────────────────────────
    print("=" * 60)
    print(f"STEP 5: Writing PR URL to bugs row {bug_id}...")
    print("=" * 60)

    url_payload = json.dumps({"pr_url": pr_url})
    stdout4, stderr4, rc4 = run(
        ["lemma", "records", "update", "bugs", bug_id, "-d", url_payload]
    )

    print(stdout4)
    if stderr4:
        print(stderr4)

    if rc4 != 0:
        print(f"[WARN] lemma records update (pr_url) exited {rc4} — PR was opened but URL not saved.")
    else:
        print(f"[OK] pr_url written: {pr_url}")


if __name__ == "__main__":
    main()
