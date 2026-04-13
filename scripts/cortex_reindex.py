#!/usr/bin/env python3
"""
Cortex Reindex — Rebuild the entire Neon index from vault files.

Reads every .md file in the vault, parses frontmatter, and upserts to Neon.
Also removes index entries for files that no longer exist on disk.

This is idempotent and safe to run anytime.

Usage:
    python cortex_reindex.py --config /path/to/.cortex/config.yaml
    python cortex_reindex.py --config /path/to/.cortex/config.yaml --dry-run
"""

import argparse
from pathlib import Path

from cortex_common import (
    load_config,
    parse_frontmatter,
    get_connection,
    find_md_files,
    upsert_note,
    TABLE_NAME,
)

import psycopg2.extras


def run_reindex(config_path, dry_run=False):
    config = load_config(config_path)
    vault_path = Path(config["vault_path"]).expanduser()

    md_files = find_md_files(vault_path)
    print(f"Found {len(md_files)} .md files in {vault_path}")

    if dry_run:
        print("\n=== DRY RUN ===")
        for f in md_files:
            fm = parse_frontmatter(f)
            if fm:
                print(f"  Would index: {f.name} -> {fm.get('title', '(no title)')}")
            else:
                print(f"  Would skip (no frontmatter): {f.name}")
        return

    conn = get_connection(config)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get current index entries to detect orphans
    cur.execute(f"SELECT file_path FROM {TABLE_NAME}")
    indexed_paths = {row["file_path"] for row in cur.fetchall()}

    # Track which paths we see on disk
    disk_paths = set()
    indexed = 0
    skipped = 0

    for md_file in md_files:
        rel_path = str(md_file.relative_to(vault_path))
        disk_paths.add(rel_path)

        try:
            fm = parse_frontmatter(md_file)
            if fm:
                upsert_note(conn, md_file, fm, config, md_files=md_files)
                indexed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  Warning: {md_file.name}: {e}")
            skipped += 1

    # Remove orphaned entries (files deleted from disk but still in index)
    orphans = indexed_paths - disk_paths
    if orphans:
        for orphan in orphans:
            cur.execute(f"DELETE FROM {TABLE_NAME} WHERE file_path = %s", (orphan,))
        print(f"Removed {len(orphans)} orphaned index entries.")

    conn.commit()
    conn.close()
    print(f"Reindex complete. Indexed {indexed}, skipped {skipped}.")


def main():
    parser = argparse.ArgumentParser(description="Cortex: full reindex")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    run_reindex(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
