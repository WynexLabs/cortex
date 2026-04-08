#!/usr/bin/env python3
"""
Cortex Setup — First-time initialization.
Creates the Postgres table in Neon and performs an initial index of all .md files.

Usage:
    python cortex_setup.py --config /path/to/.cortex/config.yaml
    python cortex_setup.py --config /path/to/.cortex/config.yaml --dry-run
"""

import argparse
import sys
from pathlib import Path

import psycopg2.sql as sql_module

from cortex_common import (
    load_config,
    parse_frontmatter,
    get_connection,
    find_md_files,
    upsert_note,
    validate_identifier,
    validate_column_type,
    TABLE_NAME,
)


# Default columns with their Postgres types
DEFAULT_COLUMNS = [
    ("file_path", "TEXT PRIMARY KEY"),
    ("title", "TEXT"),
    ("type", "TEXT DEFAULT 'note'"),
    ("status", "TEXT DEFAULT 'active'"),
    ("tags", "TEXT[]"),
    ("priority", "TEXT DEFAULT 'normal'"),
    ("created", "DATE"),
    ("updated", "DATE"),
    ("content_preview", "TEXT"),
]


def build_create_table_sql(config):
    """
    Build CREATE TABLE statement from default columns + schema extensions.
    Extension names are validated as safe identifiers.
    Extension types are validated against a whitelist.
    """
    # Start with default columns (these are hardcoded and safe)
    col_defs = [f"    {name} {definition}" for name, definition in DEFAULT_COLUMNS]

    # Add validated extension columns
    extensions = config.get("schema", {}).get("extensions", [])
    for ext in extensions:
        col_name = validate_identifier(ext["name"])
        col_type = validate_column_type(ext.get("type", "TEXT"))
        col_def = f"    {col_name} {col_type}"
        # Default values are set via ALTER TABLE with parameterized queries
        # during migration, not during initial CREATE TABLE
        col_defs.append(col_def)

    sql = f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} (\n"
    sql += ",\n".join(col_defs)
    sql += "\n);"
    return sql


def ensure_gitignore(vault_path):
    """Make sure .cortex/config.yaml is in .gitignore."""
    gitignore = vault_path / ".gitignore"
    entry = ".cortex/config.yaml"

    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content:
            return  # Already there

    with open(gitignore, "a") as f:
        f.write(f"\n# Cortex config contains database credentials\n{entry}\n")
    print(f"Added '{entry}' to .gitignore")


def run_setup(config_path, dry_run=False):
    config = load_config(config_path)
    vault_path = Path(config["vault_path"]).expanduser()

    if not vault_path.exists():
        print(f"Error: vault path does not exist: {vault_path}")
        print(f"Create it first, or update vault_path in your config.")
        sys.exit(1)

    # Ensure .gitignore protects credentials
    if not dry_run:
        ensure_gitignore(vault_path)

    # Build and execute CREATE TABLE
    create_sql = build_create_table_sql(config)

    if dry_run:
        print("=== DRY RUN — would execute: ===")
        print(create_sql)
        print()
    else:
        conn = get_connection(config)
        cur = conn.cursor()
        cur.execute(create_sql)
        conn.commit()
        print(f"Table '{TABLE_NAME}' created (or already exists).")
        conn.close()

    # Index all .md files
    md_files = find_md_files(vault_path)
    print(f"Found {len(md_files)} .md files in {vault_path}")

    if dry_run:
        for f in md_files[:5]:
            fm = parse_frontmatter(f)
            print(f"  Would index: {f.name} -> {fm.get('title', '(no title)') if fm else '(no frontmatter)'}")
        if len(md_files) > 5:
            print(f"  ... and {len(md_files) - 5} more")
        return

    conn = get_connection(config)
    indexed = 0
    skipped = 0
    for md_file in md_files:
        try:
            fm = parse_frontmatter(md_file)
            if fm:
                upsert_note(conn, md_file, fm, config)
                indexed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  Warning: skipped {md_file.name}: {e}")
            skipped += 1

    conn.commit()
    conn.close()
    print(f"\nIndexed {indexed} files, skipped {skipped}.")
    if skipped > 0:
        print(f"Skipped files have no YAML frontmatter. Add frontmatter to include them.")
    print("\nSetup complete. Test with:")
    print(f"  python cortex_query.py --config {config_path} --status active")


def main():
    parser = argparse.ArgumentParser(description="Cortex: first-time setup")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    run_setup(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
