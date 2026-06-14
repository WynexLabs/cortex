#!/usr/bin/env python3
"""Reconcile vault item-note `pr_state` / `commit` against GitHub — ground truth, never hand-typed.

For every `type: item` note with a non-empty `pr:` field, query `gh pr view` and stamp the
reconciled `pr_state` (open|draft|mergeable|merged|closed) and merge `commit` SHA into the
frontmatter. This closes the board's self-report circularity: a typed `pr_state` is stale the
instant a PR merges; a reconciled one is checkable (`git show <commit>`).

It also SURFACES stage-vs-PR mismatches (e.g. stage=shipped but PR still open) for a human/agent
to resolve — it deliberately does NOT auto-write `stage`, because stage is the judgment master.

Usage:
    python reconcile_item_pr.py --config /path/to/.cortex/config.yaml [--dry-run]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# repo-dir basename (from the item's `repo:` field) -> GitHub slug
REPO_SLUG = {
    "Project Strata": "WynexLabs/Project-Strata",
    "Project_Atlas": "WynexLabs/Project-Atlas",
}


def gh_pr_state(slug, num):
    """Return (pr_state, commit, error)."""
    r = subprocess.run(
        ["gh", "pr", "view", str(num), "--repo", slug,
         "--json", "state,isDraft,mergeStateStatus,mergeCommit"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None, None, r.stderr.strip() or "gh failed"
    d = json.loads(r.stdout)
    state = (d.get("state") or "").lower()  # open|merged|closed
    if state == "merged":
        ps = "merged"
    elif state == "closed":
        ps = "closed"
    elif d.get("isDraft"):
        ps = "draft"
    else:
        mss = (d.get("mergeStateStatus") or "").upper()
        ps = "mergeable" if mss in ("CLEAN", "HAS_HOOKS", "UNSTABLE") else "open"
    commit = ((d.get("mergeCommit") or {}).get("oid") or "")[:12]
    return ps, commit, None


def split_frontmatter(text):
    """Return (pre, fm_lines, rest) or (None, None, None) if no frontmatter."""
    if not text.startswith("---"):
        return None, None, None
    parts = text.split("\n")
    if parts[0].strip() != "---":
        return None, None, None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            return parts[0], parts[1:i], "\n".join(parts[i:])
    return None, None, None


def get_field(fm_lines, key):
    for l in fm_lines:
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", l)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def set_field(fm_lines, key, value, after_key):
    """Replace `key:` if present, else insert right after `after_key:`."""
    for i, l in enumerate(fm_lines):
        if re.match(rf"^{re.escape(key)}:", l):
            fm_lines[i] = f'{key}: "{value}"'
            return fm_lines
    for i, l in enumerate(fm_lines):
        if re.match(rf"^{re.escape(after_key)}:", l):
            fm_lines.insert(i + 1, f'{key}: "{value}"')
            return fm_lines
    fm_lines.append(f'{key}: "{value}"')
    return fm_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = Path(args.config).read_text()
    m = re.search(r"vault_path:\s*(.+)", cfg)
    vault = Path(m.group(1).strip().strip('"')).expanduser()

    items = sorted(vault.glob("projects/*/items/*.md"))
    changed, mismatches, errors, skipped = [], [], [], 0

    for f in items:
        text = f.read_text()
        pre, fm, rest = split_frontmatter(text)
        if fm is None or get_field(fm, "type") != "item":
            continue
        pr = (get_field(fm, "pr") or "").lstrip("#").strip()
        if not pr:
            skipped += 1
            continue
        repo = get_field(fm, "repo") or ""
        slug = next((s for base, s in REPO_SLUG.items() if base in repo), None)
        if not slug:
            errors.append(f"{f.name}: pr={pr} but repo '{repo}' has no known gh slug")
            continue
        ps, commit, err = gh_pr_state(slug, pr)
        if err:
            errors.append(f"{f.name}: gh pr #{pr} ({slug}) -> {err}")
            continue

        stage = get_field(fm, "stage")
        # surface (don't auto-fix) stage vs reconciled PR state
        if ps == "merged" and stage not in ("shipped",):
            mismatches.append(f"{f.name}: PR #{pr} MERGED but stage={stage} (expected shipped)")
        if ps in ("open", "draft", "mergeable") and stage == "shipped":
            mismatches.append(f"{f.name}: stage=shipped but PR #{pr} is {ps} (not merged)")

        if get_field(fm, "pr_state") == ps and get_field(fm, "commit") == commit:
            continue
        set_field(fm, "pr_state", ps, "pr")
        set_field(fm, "commit", commit, "pr_state")
        changed.append(f"{f.name}: pr_state={ps} commit={commit or '(none)'}")
        if not args.dry_run:
            f.write_text(pre + "\n" + "\n".join(fm) + "\n" + rest)

    print(f"=== reconcile_item_pr {'(DRY RUN) ' if args.dry_run else ''}===")
    print(f"items scanned: {len(items)} | with pr: {len(items)-skipped if False else '...'}")
    print(f"\nUPDATED ({len(changed)}):")
    for c in changed:
        print("  " + c)
    print(f"\nSTAGE MISMATCHES ({len(mismatches)}) — resolve by hand, stage is the judgment master:")
    for m_ in mismatches:
        print("  ⚠ " + m_)
    print(f"\nERRORS ({len(errors)}):")
    for e in errors:
        print("  ✗ " + e)


if __name__ == "__main__":
    main()
