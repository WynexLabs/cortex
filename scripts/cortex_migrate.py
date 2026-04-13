#!/usr/bin/env python3
"""
Cortex Migrate — Add new schema fields to the Postgres table.

When users add new fields to schema.extensions in their config,
run this to add the corresponding columns to the Neon table.

Usage:
    python cortex_migrate.py --config /path/to/.cortex/config.yaml
    python cortex_migrate.py --config /path/to/.cortex/config.yaml --dry-run
"""

import argparse
import psycopg2.sql as sql_module

from cortex_common import (
    load_config,
    get_connection,
    validate_identifier,
    validate_column_type,
    TABLE_NAME,
    LINKS_TABLE_NAME,
    HEADINGS_TABLE_NAME,
)


# v1.4 core schema additions. Each step is idempotent.
CORE_MIGRATIONS_V1_4 = [
    # New columns on cortex_notes
    ("v1.4: cortex_notes.body",
     f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS body TEXT"),
    ("v1.4: cortex_notes.summary",
     f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS summary TEXT"),
    ("v1.4: cortex_notes.aliases",
     f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS aliases TEXT[]"),
    ("v1.4: cortex_notes.supersedes",
     f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS supersedes TEXT"),
    # tsvector full-text-search index on body
    ("v1.4: cortex_notes.body_tsv (generated column)",
     f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS body_tsv tsvector "
     f"GENERATED ALWAYS AS (to_tsvector('english', coalesce(body,''))) STORED"),
    ("v1.4: GIN index on cortex_notes.body_tsv",
     f"CREATE INDEX IF NOT EXISTS cortex_notes_body_tsv_idx "
     f"ON {TABLE_NAME} USING GIN(body_tsv)"),
    # cortex_links table
    ("v1.4: cortex_links table",
     f"CREATE TABLE IF NOT EXISTS {LINKS_TABLE_NAME} ("
     f"  source_path TEXT NOT NULL REFERENCES {TABLE_NAME}(file_path) ON DELETE CASCADE,"
     f"  target_path TEXT NOT NULL,"
     f"  target_resolved BOOLEAN NOT NULL,"
     f"  link_type TEXT NOT NULL CHECK (link_type IN ('wikilink','see_also','supersedes')),"
     f"  position INT,"
     f"  PRIMARY KEY (source_path, target_path, link_type)"
     f")"),
    ("v1.4: cortex_links target index",
     f"CREATE INDEX IF NOT EXISTS cortex_links_target_idx "
     f"ON {LINKS_TABLE_NAME}(target_path)"),
    # cortex_headings table
    ("v1.4: cortex_headings table",
     f"CREATE TABLE IF NOT EXISTS {HEADINGS_TABLE_NAME} ("
     f"  file_path TEXT NOT NULL REFERENCES {TABLE_NAME}(file_path) ON DELETE CASCADE,"
     f"  level INT NOT NULL CHECK (level BETWEEN 1 AND 6),"
     f"  text TEXT NOT NULL,"
     f"  anchor TEXT NOT NULL,"
     f"  position INT NOT NULL,"
     f"  PRIMARY KEY (file_path, position)"
     f")"),
    ("v1.4: cortex_headings anchor index",
     f"CREATE INDEX IF NOT EXISTS cortex_headings_anchor_idx "
     f"ON {HEADINGS_TABLE_NAME}(anchor)"),
]


def run_core_migrations(conn, dry_run=False):
    """Apply baseline v1.4+ schema additions. Idempotent — safe to re-run."""
    cur = conn.cursor()
    applied = 0
    for label, sql in CORE_MIGRATIONS_V1_4:
        if dry_run:
            print(f"  Would apply: {label}")
            continue
        cur.execute(sql)
        print(f"  Applied: {label}")
        applied += 1
    return applied


def get_existing_columns(conn):
    """Get the current column names from the table."""
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (TABLE_NAME,)
    )
    return {row[0] for row in cur.fetchall()}


def run_migrate(config_path, dry_run=False):
    config = load_config(config_path)
    conn = get_connection(config)

    print("Running core v1.4 schema migrations...")
    core_count = run_core_migrations(conn, dry_run=dry_run)
    if not dry_run:
        conn.commit()
    print(f"Core migrations: {core_count} step(s) applied.\n")

    extensions = config.get("schema", {}).get("extensions", [])
    if not extensions:
        print("No user schema extensions defined in config.")
        conn.close()
        return

    existing = get_existing_columns(conn)

    to_add = []
    for ext in extensions:
        col_name = validate_identifier(ext["name"])
        if col_name not in existing:
            col_type = validate_column_type(ext.get("type", "TEXT"))
            default = ext.get("default")
            to_add.append((col_name, col_type, default))

    if not to_add:
        print("All extension columns already exist. Nothing to migrate.")
        conn.close()
        return

    for col_name, col_type, default in to_add:
        # Use psycopg2.sql for safe identifier quoting
        # Column type is validated against a whitelist, so it's safe to interpolate
        alter = sql_module.SQL("ALTER TABLE {} ADD COLUMN {} " + col_type).format(
            sql_module.Identifier(TABLE_NAME),
            sql_module.Identifier(col_name),
        )

        if default is not None:
            # Use parameterized default value
            alter = sql_module.SQL(
                "ALTER TABLE {} ADD COLUMN {} " + col_type + " DEFAULT %s"
            ).format(
                sql_module.Identifier(TABLE_NAME),
                sql_module.Identifier(col_name),
            )

        if dry_run:
            print(f"Would add column: {col_name} ({col_type})"
                  + (f" DEFAULT '{default}'" if default else ""))
        else:
            cur = conn.cursor()
            if default is not None:
                cur.execute(alter, (default,))
            else:
                cur.execute(alter)
            print(f"Added column: {col_name} ({col_type})")

    if not dry_run:
        conn.commit()

    conn.close()
    print(f"Migration complete. Added {len(to_add)} column(s).")


def main():
    parser = argparse.ArgumentParser(description="Cortex: migrate schema extensions")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    run_migrate(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
