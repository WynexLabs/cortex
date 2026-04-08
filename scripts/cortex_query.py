#!/usr/bin/env python3
"""
Cortex Query — Query your vault to find relevant notes.

Uses Neon if configured (fast SQL), otherwise falls back to local file scanning.
Works at any setup level.

Usage:
    # Search by keyword
    python cortex_query.py --config /path/to/.cortex/config.yaml --search "rate limiting"

    # Filter by type and status
    python cortex_query.py --config /path/to/.cortex/config.yaml --type project --status active

    # Filter by tag
    python cortex_query.py --config /path/to/.cortex/config.yaml --tag deployment

    # Output as JSON (for piping to other tools)
    python cortex_query.py --config /path/to/.cortex/config.yaml --search "auth" --json

    # Show current setup level
    python cortex_query.py --config /path/to/.cortex/config.yaml --level
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cortex_common import (
    load_config, get_connection, has_neon, local_query,
    print_setup_level, TABLE_NAME,
)


def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def query_via_neon(config, args):
    """Query using Neon Postgres (Level 3)."""
    import psycopg2.extras

    conn = get_connection(config)
    conditions = []
    params = []

    if args.filter:
        # Raw SQL — advanced/scripting only, not for user input
        full = f"SELECT * FROM {TABLE_NAME} WHERE {args.filter} ORDER BY updated DESC"
        if args.limit:
            full += f" LIMIT {int(args.limit)}"
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(full, [])
        results = [dict(row) for row in cur.fetchall()]
        conn.close()
        return results

    if args.search:
        conditions.append("(title ILIKE %s OR content_preview ILIKE %s)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])
    if args.type:
        conditions.append("type = %s")
        params.append(args.type)
    if args.status:
        conditions.append("status = %s")
        params.append(args.status)
    if args.tag:
        conditions.append("%s = ANY(tags)")
        params.append(args.tag)
    if args.priority:
        conditions.append("priority = %s")
        params.append(args.priority)
    if args.since:
        conditions.append("updated >= %s")
        params.append(args.since)

    sql = f"SELECT * FROM {TABLE_NAME}"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY updated DESC"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    results = [dict(row) for row in cur.fetchall()]
    conn.close()
    return results


def query_via_local(config, args):
    """Query by scanning local files (Level 0-2, no Neon needed)."""
    return local_query(
        vault_path=config["vault_path"],
        search=args.search,
        type_filter=args.type,
        status_filter=args.status,
        tag_filter=args.tag,
        priority_filter=args.priority,
        limit=args.limit,
    )


def display_results(results, as_json=False):
    if not results:
        if as_json:
            print(json.dumps([], indent=2))
        else:
            print("No matching notes found.")
        return

    if as_json:
        print(json.dumps(results, indent=2, default=json_serial))
    else:
        print(f"Found {len(results)} note(s):\n")
        for r in results:
            tags = ", ".join(r.get("tags", []) or [])
            print(f"  [{r.get('type', '?')}] {r.get('title', '(untitled)')}")
            print(f"    Path:     {r['file_path']}")
            print(f"    Status:   {r.get('status', '?')}  |  Priority: {r.get('priority', '?')}")
            if tags:
                print(f"    Tags:     {tags}")
            preview = r.get("content_preview", "")
            if preview:
                print(f"    Preview:  {preview[:80]}...")
            print()


def main():
    parser = argparse.ArgumentParser(description="Cortex: query your vault")
    parser.add_argument("--config", required=True, help="Path to .cortex/config.yaml")
    parser.add_argument("--filter", help="Raw SQL WHERE clause (advanced, Neon only)")
    parser.add_argument("--search", help="Keyword search across title and content")
    parser.add_argument("--type", help="Filter by note type")
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--tag", help="Filter by tag")
    parser.add_argument("--priority", help="Filter by priority")
    parser.add_argument("--since", help="Filter by updated date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, help="Max results to return")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    parser.add_argument("--level", action="store_true", help="Show current setup level")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.level:
        print_setup_level(config)
        return

    # Use Neon if available, otherwise fall back to local scanning
    if has_neon(config):
        try:
            results = query_via_neon(config, args)
            display_results(results, args.json_output)
            return
        except Exception as e:
            print(f"  Neon query failed ({e}), falling back to local scan...")

    # Local fallback
    if args.filter:
        print("  --filter requires Neon. Use --search, --type, --tag etc. for local queries.")
        sys.exit(1)

    results = query_via_local(config, args)
    display_results(results, args.json_output)


if __name__ == "__main__":
    main()
