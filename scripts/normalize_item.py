#!/usr/bin/env python3
"""Normalize raw `nemotron-3-super` output into a clean, lint-passing vault item note.

The structure (frontmatter) is built DETERMINISTICALLY from known-good args, so the
model's fence/field/ordering artifacts (the 86%-at-volume failure modes) become impossible.
Only the *content* is taken from the model: the summary sentence + Read-first + Lessons.
Read-first is kept lint-safe by construction: the project backlog link (always resolves) plus
any `repo:`/code path the model surfaced — never a danglable wikilink.

Usage:
  normalize_item.py --project strata --slug foo --repo "~/Developer/WynexLabs/Project Strata" \
    --kind feature --sprint bar --rank 2 [--stage shaping] [--owner wutti] \
    [--date 2026-06-15] [--summary "<gist fallback>"]  < raw_nemotron.md  > item.md
"""
import argparse
import re
import sys

VALID_KINDS = {"feature", "infra", "bug", "chore"}
VALID_STAGES = {"shaping", "approved", "building", "verifying", "gate", "shipped"}


def strip_code_fence(text):
    # drop a leading ```markdown / ``` wrapper and a trailing ``` if present
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
    t = re.sub(r"\n```\s*$", "", t)
    return t


def bullets_under(text, heading):
    m = re.search(rf"^##\s+{re.escape(heading)}.*$", text, re.M | re.I)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    if nxt:
        rest = rest[:nxt.start()]
    out, seen = [], set()
    for line in rest.splitlines():
        s = line.strip()
        if not s or not s[:1] in ("-", "*"):
            continue
        if re.fullmatch(r"[-*_]{3,}", s):       # markdown horizontal rule / stray fence, not a bullet
            continue
        content = s[1:].strip()
        if not content or content.startswith("<!--"):
            continue
        if re.fullmatch(r"[-*_]+", content):     # e.g. "- --" left by a dropped frontmatter fence
            continue
        b = "- " + content
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def extract_summary(text):
    m = re.search(r"^\s*summary:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip().strip('"').strip("'").strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    for a in ("project", "slug", "repo", "kind", "sprint", "rank"):
        ap.add_argument("--" + a, required=True)
    ap.add_argument("--stage", default="shaping")
    ap.add_argument("--owner", default="wutti")
    ap.add_argument("--date", default="2026-06-15")
    ap.add_argument("--summary", default="")
    ap.add_argument("--code", default="", help="comma-separated repo-relative paths for Read-first")
    ap.add_argument("--lesson", default="", help="the Lessons & Decisions bullet text")
    args = ap.parse_args()

    if args.kind not in VALID_KINDS:
        sys.exit(f"bad kind: {args.kind}")
    if args.stage not in VALID_STAGES:
        sys.exit(f"bad stage: {args.stage}")

    raw = strip_code_fence(sys.stdin.read())

    summary = extract_summary(raw) or args.summary or args.slug.replace("-", " ")
    summary = summary.replace('"', "'").strip()

    # Read-first: backlog (always resolves) + triage-supplied code paths + any path the model surfaced.
    backlog = f"- [[projects/{args.project}/backlog]]"
    arg_code = [f"- `repo:{p.strip()}`" for p in args.code.split(",") if p.strip()]
    model_code = [b for b in bullets_under(raw, "Read-first") if "repo:" in b]
    readfirst, seen = [backlog], {backlog}
    for b in arg_code + model_code:
        if b not in seen:
            seen.add(b)
            readfirst.append(b)

    if args.lesson.strip():
        lessons = ["- " + args.lesson.strip()]
    else:
        lessons = bullets_under(raw, "Lessons & Decisions") or bullets_under(raw, "Lessons")
    if not lessons:
        lessons = [f"- Converted from the {args.project} backlog tail (board migration {args.date})."]
    lessons = lessons[:2]

    repo = "" if args.repo.strip('"') in ("", "''") else args.repo

    fm = [
        "---", "type: item", f"project: {args.project}", f'repo: "{repo}"',
        f"stage: {args.stage}", 'gate: ""', f"kind: {args.kind}", f"sprint: {args.sprint}",
        f"rank: {args.rank}", 'deadline: ""', f"owner: {args.owner}", 'pr: ""',
        'pr_state: ""', 'commit: ""', "status: active",
        f"created: {args.date}", f"updated: {args.date}", f'summary: "{summary}"', "---",
    ]
    body = ["", "## Read-first"] + readfirst + ["", "## Lessons & Decisions"] + lessons + [""]
    sys.stdout.write("\n".join(fm) + "\n" + "\n".join(body))


if __name__ == "__main__":
    main()
