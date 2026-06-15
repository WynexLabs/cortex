#!/usr/bin/env python3
"""
Cortex Lint — Check vault notes against the LLM-first conventions.

Runs 7 deterministic checks across the vault. Never modifies files. Never
blocks indexing. Outputs a report grouped by note.

Lint covers 7 of the 10 LLM-vault conventions. The other 3 (aliases, see-also,
source) are optional or require human judgment and are intentionally not
mechanically enforced.

Usage:
    python cortex_lint.py --config /path/to/.cortex/config.yaml
    python cortex_lint.py --config ... --json
    python cortex_lint.py --config ... --ci      # exit 1 if any warnings
    python cortex_lint.py --config ... --note projects/strata/README.md
"""

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cortex_common import (
    load_config, find_md_files, parse_frontmatter,
    extract_wikilinks, extract_headings, resolve_link, slugify,
    VALID_STATUSES, VALID_PRIORITIES,
)


# Heuristic: an H2 section opener that begins with one of these is likely
# a pronoun referring to something outside the section's context.
PRONOUN_OPENERS = {"it", "this", "they", "these", "that", "those"}

# Long-note threshold for requiring a leading ## Summary heading
LONG_NOTE_WORDS = 500
# Atomic ceiling — beyond either, propose split
ATOMIC_MAX_H2 = 3
ATOMIC_MAX_WORDS = 600
# Structured/session records — exempt from atomic-ceiling + summary-H2 (those rules target atomic knowledge notes)
STRUCTURED_TYPES = {"log", "backlog", "spec"}

# --- Item-note (board) schema — local anti-drift enforcement for the vault board
VALID_STAGES = {"shaping", "approved", "building", "verifying", "gate", "shipped"}
VALID_KINDS = {"feature", "infra", "bug", "chore"}
ITEM_REQUIRED = ("stage", "owner", "kind", "sprint", "rank")
ITEM_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def word_count(text):
    return len(re.findall(r"\b\w+\b", text or ""))


def first_sentence_after_heading(body, heading_position):
    """Return the first non-blank, non-heading line after heading_position."""
    after = body[heading_position:]
    lines = after.split("\n")[1:]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return None
        return stripped
    return None


def check_item_schema(fm):
    """Validate a `type: item` board note so its state stays trustworthy.

    The board (Obsidian Bases) and a resuming agent both read this frontmatter
    as truth — these checks are the local anti-drift layer that stops a typed
    `stage`/`gate`/`owner` from silently lying.
    """
    warnings = []

    for field in ITEM_REQUIRED:
        val = fm.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            warnings.append({
                "rule": "item-missing-field",
                "severity": "warning",
                "msg": f"Item missing required `{field}:`",
            })

    stage = fm.get("stage")
    if stage and stage not in VALID_STAGES:
        warnings.append({
            "rule": "item-unknown-stage",
            "severity": "warning",
            "msg": f"Unknown stage '{stage}' (known: {', '.join(sorted(VALID_STAGES))})",
        })

    kind = fm.get("kind")
    if kind and kind not in VALID_KINDS:
        warnings.append({
            "rule": "item-unknown-kind",
            "severity": "warning",
            "msg": f"Unknown kind '{kind}' (known: {', '.join(sorted(VALID_KINDS))})",
        })

    if stage == "gate" and not fm.get("gate"):
        warnings.append({
            "rule": "item-gate-without-reason",
            "severity": "warning",
            "msg": "stage is `gate` but `gate:` reason is empty — a gated card must say why",
        })

    owner = fm.get("owner")
    if owner is not None and not isinstance(owner, str):
        warnings.append({
            "rule": "item-owner-not-single",
            "severity": "warning",
            "msg": f"`owner:` must be exactly one holder (got {type(owner).__name__}) "
                   f"— one writer per item (baton), never a list",
        })

    deadline = fm.get("deadline")
    if deadline is not None and str(deadline).strip():
        ok = isinstance(deadline, datetime.date) or bool(ITEM_DATE_RE.match(str(deadline)))
        if not ok:
            warnings.append({
                "rule": "item-bad-deadline",
                "severity": "warning",
                "msg": f"`deadline:` must be a YYYY-MM-DD date (got '{deadline}')",
            })

    return warnings


def check_item_readfirst(body):
    """The `## Read-first` manifest is THE agent affordance — enforce it exists and is non-empty.

    A resuming agent (or dispatched subagent) loads this list to know what to read.
    An empty/missing manifest is the keystone hole the 2026-06-14 cold-resume test found.
    Resolution of any [[wikilinks]] inside it is already covered by Check 4 (dangling-wikilink).
    """
    warnings = []
    m = re.search(r"^##\s+Read-first\s*$", body or "", re.MULTILINE | re.IGNORECASE)
    if not m:
        warnings.append({
            "rule": "item-readfirst-missing",
            "severity": "warning",
            "msg": "Item has no `## Read-first` manifest — a resuming agent can't know what to load",
        })
        return warnings

    # Section = from after the heading to the next H2 (or EOF)
    section = body[m.end():]
    nxt = re.search(r"^##\s+", section, re.MULTILINE)
    if nxt:
        section = section[:nxt.start()]

    # A real entry = a bullet whose content isn't just an HTML comment / whitespace
    has_entry = False
    for line in section.splitlines():
        s = line.strip()
        if not s or s.startswith("<!--") or s.startswith("-->"):
            continue
        if s[:1] in ("-", "*"):
            content = s[1:].strip()
            if content and not content.startswith("<!--"):
                has_entry = True
                break
    if not has_entry:
        warnings.append({
            "rule": "item-readfirst-empty",
            "severity": "warning",
            "msg": "`## Read-first` is empty — list the 2-4 notes/files a fresh agent must read first",
        })
    return warnings


def check_note(note_path, vault_path, md_files):
    """Run all 7 checks on a single note. Returns list of warning dicts."""
    warnings = []
    rel_path = str(note_path.relative_to(vault_path))

    # _claude/templates/ hold scaffolding with {{placeholders}} (invalid YAML by design) — not real notes
    if rel_path.startswith("_claude/templates/") or rel_path.startswith("_claude\\templates\\"):
        return warnings

    # projects/BOARD.md is generated by cortex_board.py — not an authored note
    if rel_path == "projects/BOARD.md" or rel_path.endswith("/BOARD.md"):
        return warnings

    fm = parse_frontmatter(note_path)

    if fm is None:
        warnings.append({
            "rule": "frontmatter-missing",
            "severity": "warning",
            "msg": "No YAML frontmatter found",
            "file_path": rel_path,
        })
        return warnings

    body = fm.get("_body", "")
    wc = word_count(body)
    headings = extract_headings(body)
    h2s = [(t, p) for lvl, t, p in headings if lvl == 2]
    note_type = fm.get("type")

    # Check 1: Missing summary frontmatter
    if not fm.get("summary"):
        warnings.append({
            "rule": "missing-summary-frontmatter",
            "severity": "warning",
            "msg": "Missing `summary:` frontmatter (1-3 sentence TLDR)",
        })

    # Check 2: Long note missing ## Summary H2 (atomic/knowledge notes only — not session/structured records)
    if wc >= LONG_NOTE_WORDS and note_type not in STRUCTURED_TYPES:
        first_h2 = h2s[0][0] if h2s else None
        if not first_h2 or slugify(first_h2) != "summary":
            warnings.append({
                "rule": "missing-summary-h2",
                "severity": "warning",
                "msg": f"Note has {wc} words but no `## Summary` as first H2",
            })

    # Check 3: Atomic ceiling (atomic/knowledge notes only — logs/backlogs/specs are structured records)
    if note_type not in STRUCTURED_TYPES and (len(h2s) > ATOMIC_MAX_H2 or wc > ATOMIC_MAX_WORDS):
        warnings.append({
            "rule": "atomic-ceiling-exceeded",
            "severity": "warning",
            "msg": f"Exceeds atomic ceiling: {len(h2s)} H2 sections, {wc} words "
                   f"(max {ATOMIC_MAX_H2} H2 OR ~{ATOMIC_MAX_WORDS} words)",
        })

    # Check 4: Dangling wikilinks
    dangling = []
    for target, _ in extract_wikilinks(body):
        resolved, found = resolve_link(target, vault_path, md_files)
        if not found:
            dangling.append(target)
    for d in dangling:
        warnings.append({
            "rule": "dangling-wikilink",
            "severity": "warning",
            "msg": f"Wikilink target not found: [[{d}]]",
        })

    # Check 5: Pronoun heuristic at H2 openers
    for h2_text, h2_pos in h2s:
        first = first_sentence_after_heading(body, h2_pos)
        if not first:
            continue
        first_word = re.match(r"[A-Za-z']+", first)
        if first_word and first_word.group(0).lower() in PRONOUN_OPENERS:
            warnings.append({
                "rule": "pronoun-opener-at-h2",
                "severity": "warning",
                "msg": f"Section '{h2_text}' opens with pronoun '{first_word.group(0)}' "
                       f"— name the entity instead",
            })

    # Check 6: Frontmatter validation
    status = fm.get("status")
    if status and status not in VALID_STATUSES:
        warnings.append({
            "rule": "unknown-status",
            "severity": "warning",
            "msg": f"Unknown status '{status}' (known: {', '.join(sorted(VALID_STATUSES))})",
        })
    priority = fm.get("priority")
    if priority and priority not in VALID_PRIORITIES:
        warnings.append({
            "rule": "unknown-priority",
            "severity": "warning",
            "msg": f"Unknown priority '{priority}' (known: {', '.join(sorted(VALID_PRIORITIES))})",
        })
    if not fm.get("created"):
        warnings.append({
            "rule": "missing-created-date",
            "severity": "warning",
            "msg": "Missing `created:` frontmatter date",
        })
    if not fm.get("updated"):
        warnings.append({
            "rule": "missing-updated-date",
            "severity": "warning",
            "msg": "Missing `updated:` frontmatter date",
        })

    # Check 7: Heading slug collision within file
    slug_seen = defaultdict(list)
    for level, text, _ in headings:
        slug_seen[slugify(text)].append((level, text))
    for slug, entries in slug_seen.items():
        if len(entries) > 1:
            warnings.append({
                "rule": "heading-slug-collision",
                "severity": "warning",
                "msg": f"Heading slug '{slug}' appears {len(entries)} times: "
                       f"{', '.join(t for _, t in entries)}",
            })

    # Item-schema checks (board state enforcement — type: item only)
    if fm.get("type") == "item":
        warnings.extend(check_item_schema(fm))
        warnings.extend(check_item_readfirst(body))

    for w in warnings:
        w["file_path"] = rel_path
    return warnings


def run_lint(config_path, json_output=False, ci_mode=False, single_note=None):
    config = load_config(config_path)
    vault_path = Path(config["vault_path"]).expanduser()
    md_files = find_md_files(vault_path)

    if single_note:
        target = (vault_path / single_note).resolve()
        if not target.exists():
            print(f"Note not found: {single_note}", file=sys.stderr)
            sys.exit(1)
        files_to_check = [target]
    else:
        files_to_check = md_files

    all_warnings = []
    for f in files_to_check:
        all_warnings.extend(check_note(f, vault_path, md_files))

    if json_output:
        print(json.dumps(all_warnings, indent=2))
    else:
        if not all_warnings:
            print(f"Lint clean. {len(files_to_check)} note(s) checked.")
        else:
            by_file = defaultdict(list)
            for w in all_warnings:
                by_file[w["file_path"]].append(w)
            print(f"Found {len(all_warnings)} warning(s) across "
                  f"{len(by_file)} note(s):\n")
            for file_path in sorted(by_file):
                print(f"  {file_path}")
                for w in by_file[file_path]:
                    print(f"    [{w['rule']}] {w['msg']}")
                print()

    if ci_mode and all_warnings:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Cortex: lint vault notes against LLM-first conventions")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON for programmatic consumption")
    parser.add_argument("--ci", action="store_true",
                        help="Exit code 1 if any warnings (for CI workflows)")
    parser.add_argument("--note", metavar="REL_PATH",
                        help="Lint a single note instead of the whole vault")
    args = parser.parse_args()
    run_lint(args.config, json_output=args.json_output,
             ci_mode=args.ci, single_note=args.note)


if __name__ == "__main__":
    main()
