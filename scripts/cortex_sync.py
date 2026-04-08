#!/usr/bin/env python3
"""
Cortex Sync — Sync your vault.

What it does depends on your setup level:
- Level 0-1: Validates frontmatter across files (auto-repairs issues)
- Level 2: + git commit and push
- Level 3: + upserts frontmatter to Neon

Usage:
    # Sync a single file
    python cortex_sync.py --config /path/to/.cortex/config.yaml --file /path/to/note.md

    # Sync all files
    python cortex_sync.py --config /path/to/.cortex/config.yaml --all

    # Dry run
    python cortex_sync.py --config /path/to/.cortex/config.yaml --all --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cortex_common import (
    load_config,
    parse_frontmatter,
    validate_frontmatter,
    get_connection,
    has_neon,
    has_git,
    get_setup_level,
    find_md_files,
    upsert_note,
    git_commit_and_push,
)


def git_changed_files(vault_path):
    """Get list of .md files that have been modified or added according to git."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=vault_path
        )
        changed = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            filepath = line[3:].strip()
            if filepath.endswith(".md"):
                full_path = Path(vault_path) / filepath
                if full_path.exists():
                    changed.append(full_path)
        return changed
    except FileNotFoundError:
        return find_md_files(vault_path)


def run_sync(config_path, file_path=None, sync_all=False, dry_run=False):
    config = load_config(config_path)
    vault_path = Path(config["vault_path"]).expanduser()
    level = get_setup_level(config)

    print(f"  Setup level: {level}/3", end="")
    if level < 3:
        print(f" (no {'Neon' if level == 2 else 'git' if level < 2 else ''})", end="")
    print()

    # Determine which files to sync
    if file_path:
        files = [Path(file_path).resolve()]
    elif sync_all:
        files = find_md_files(vault_path)
    elif has_git(config):
        files = git_changed_files(vault_path)
    else:
        files = find_md_files(vault_path)

    if not files:
        print("No files to sync.")
        return

    print(f"Syncing {len(files)} file(s)...")

    if dry_run:
        for f in files:
            fm = parse_frontmatter(f)
            title = fm.get("title", f.stem) if fm else "(no frontmatter)"
            print(f"  Would sync: {f.name} -> {title}")
        return

    # Always: validate frontmatter (Level 0+)
    conn = get_connection(config) if has_neon(config) else None
    synced = 0
    validated = 0
    skipped = 0

    for md_file in files:
        try:
            fm = parse_frontmatter(md_file)
            if fm:
                # Validate (works at all levels)
                fm_v, warnings = validate_frontmatter(fm)
                validated += 1
                for w in warnings:
                    print(f"  Fixed ({md_file.name}): {w}")

                # Upsert to Neon (Level 3 only)
                if conn:
                    upsert_note(conn, md_file, fm, config)
                    synced += 1
                    print(f"  Indexed: {md_file.name}")
                else:
                    print(f"  Validated: {md_file.name}")
            else:
                skipped += 1
                print(f"  Skipped (no frontmatter): {md_file.name}")
        except Exception as e:
            print(f"  Error: {md_file.name}: {e}")
            skipped += 1

    if conn:
        conn.commit()
        conn.close()

    print(f"\nDone. Validated {validated}, indexed {synced}, skipped {skipped}.")

    # Git integration (Level 2+)
    if has_git(config):
        git_commit_and_push(vault_path, files, config)
    else:
        print("  (Git not configured — files saved locally only)")


def main():
    parser = argparse.ArgumentParser(description="Cortex: sync your vault")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--file", help="Sync a single file")
    parser.add_argument("--all", action="store_true", dest="sync_all", help="Sync all .md files")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    run_sync(args.config, file_path=args.file, sync_all=args.sync_all, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
