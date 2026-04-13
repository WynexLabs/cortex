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


def check_note(note_path, vault_path, md_files):
    """Run all 7 checks on a single note. Returns list of warning dicts."""
    warnings = []
    rel_path = str(note_path.relative_to(vault_path))
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

    # Check 1: Missing summary frontmatter
    if not fm.get("summary"):
        warnings.append({
            "rule": "missing-summary-frontmatter",
            "severity": "warning",
            "msg": "Missing `summary:` frontmatter (1-3 sentence TLDR)",
        })

    # Check 2: Long note missing ## Summary H2
    if wc >= LONG_NOTE_WORDS:
        first_h2 = h2s[0][0] if h2s else None
        if not first_h2 or slugify(first_h2) != "summary":
            warnings.append({
                "rule": "missing-summary-h2",
                "severity": "warning",
                "msg": f"Note has {wc} words but no `## Summary` as first H2",
            })

    # Check 3: Atomic ceiling
    if len(h2s) > ATOMIC_MAX_H2 or wc > ATOMIC_MAX_WORDS:
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
