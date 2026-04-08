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
)


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
    extensions = config.get("schema", {}).get("extensions", [])

    if not extensions:
        print("No schema extensions defined in config. Nothing to migrate.")
        return

    conn = get_connection(config)
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
