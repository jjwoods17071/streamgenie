#!/usr/bin/env python3
"""
Alignment crawl — does recent work still serve the product objective?

selftest.py answers "is it broken?". This answers the question a test suite structurally
cannot: "is this the right thing, is it in the right layer, and what QA is missing?"

    python review.py                # working tree vs HEAD
    python review.py --since HEAD~5 # a batch of commits
    python review.py --files a.py b.py

ADVISORY ONLY. Always exits 0. It is a reviewer, not a gate — a build that fails on a
model's opinion is a build nobody trusts.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_DIFF_CHARS = 60_000

SYSTEM = """You are reviewing changes to StreamGenie against its own stated product \
objective and working agreement, both of which are given to you. You are not a linter — \
correctness is covered by a test suite. Judge FIT.

For each finding be specific and cite the file. Prefer few sharp observations over many \
weak ones; returning an empty list is a valid and useful answer.

Judge against these, in order:
1. PRODUCT OBJECTIVE — does this make "what do I watch tonight, and where is it?" faster \
to answer? If it doesn't, is there a stated reason?
2. LAYERING — business logic belongs in the importable modules (recs, milestones, movies, \
tmdb, newsletter), not in app.py. Native clients are the direction; anything that lands \
only in app.py gets written twice.
3. PRINCIPLES — actionable before complete; answer then inventory; never guess at \
availability; degrade rather than fail; poster art over text.
4. QA GAPS — what could break that nothing would catch? Name the check that's missing, \
especially for anything only reachable at render time.
5. REFERENCE APPS — where a layout decision was invented that Netflix or Apple TV has \
already solved, say which and how.

Be concrete about what to do next. Do not restate what the diff obviously does."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "description": "One sentence: does this batch serve the objective?"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["objective", "layering", "principle", "qa-gap", "reference"]},
                    "file": {"type": "string"},
                    "note": {"type": "string", "description": "What's off, in one or two sentences"},
                    "suggestion": {"type": "string", "description": "The concrete next step"},
                },
                "required": ["kind", "file", "note", "suggestion"],
                "additionalProperties": False,
            },
        },
        "next_tests": {
            "type": "array",
            "description": "Specific checks worth adding to selftest.py",
            "items": {"type": "string"},
        },
    },
    "required": ["verdict", "findings", "next_tests"],
    "additionalProperties": False,
}

COLOR = {"objective": "\033[35m", "layering": "\033[36m", "principle": "\033[33m",
         "qa-gap": "\033[31m", "reference": "\033[34m"}


def read(name):
    path = os.path.join(HERE, name)
    return open(path).read() if os.path.exists(path) else ""


def get_diff(args):
    if args.files:
        return subprocess.run(["git", "diff", "--", *args.files], cwd=HERE,
                              capture_output=True, text=True).stdout
    if args.since:
        return subprocess.run(["git", "diff", args.since, "--"], cwd=HERE,
                              capture_output=True, text=True).stdout
    out = subprocess.run(["git", "diff", "HEAD"], cwd=HERE, capture_output=True, text=True).stdout
    return out or subprocess.run(["git", "diff", "HEAD~1", "--"], cwd=HERE,
                                 capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="git ref to diff against (e.g. HEAD~5)")
    ap.add_argument("--files", nargs="*", help="limit to these files")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, ".env"))
    except Exception:
        pass

    diff = get_diff(args)
    if not diff.strip():
        print("Nothing to review — no diff.")
        return 0
    truncated = len(diff) > MAX_DIFF_CHARS
    if truncated:
        diff = diff[:MAX_DIFF_CHARS]

    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ANTHROPIC_API_KEY not set — review skipped.")
        return 0

    payload = (f"PRODUCT.md\n----------\n{read('PRODUCT.md')}\n\n"
               f"CLAUDE.md (working agreement)\n-----------------------------\n{read('CLAUDE.md')}\n\n"
               f"DIFF UNDER REVIEW{' (truncated)' if truncated else ''}\n-----------------\n{diff}")

    import anthropic
    r = anthropic.Anthropic(api_key=key).messages.create(
        model=os.getenv("GENIE_CLAUDE_MODEL", "claude-sonnet-4-5"),
        max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": payload}],
    )
    text = "".join(b.text for b in r.content if b.type == "text")
    data = json.loads(text)

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print(f"\n\033[1mVerdict\033[0m  {data['verdict']}\n")
    if not data["findings"]:
        print("  No alignment concerns.\n")
    for f in data["findings"]:
        c = COLOR.get(f["kind"], "")
        print(f"  {c}[{f['kind']}]\033[0m {f['file']}")
        print(f"      {f['note']}")
        print(f"      \033[2m→ {f['suggestion']}\033[0m\n")
    if data["next_tests"]:
        print("\033[1mSuggested checks\033[0m")
        for t in data["next_tests"]:
            print(f"  · {t}")
    print("\n\033[2madvisory only — this never fails a build\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
