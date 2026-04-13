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
    print_setup_level, TABLE_NAME, LINKS_TABLE_NAME, HEADINGS_TABLE_NAME,
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


def query_backlinks(config, target_path):
    """List notes that link TO target_path. Requires Neon."""
    import psycopg2.extras
    conn = get_connection(config)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"SELECT source_path, link_type, position FROM {LINKS_TABLE_NAME} "
        f"WHERE target_path = %s ORDER BY link_type, source_path",
        (target_path,),
    )
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def query_forward_links(config, source_path):
    """List notes that source_path links TO. Requires Neon."""
    import psycopg2.extras
    conn = get_connection(config)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"SELECT target_path, target_resolved, link_type, position FROM {LINKS_TABLE_NAME} "
        f"WHERE source_path = %s ORDER BY position NULLS LAST",
        (source_path,),
    )
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def query_fts(config, query, limit=None):
    """Full-text search across note bodies via tsvector. Requires Neon."""
    import psycopg2.extras
    conn = get_connection(config)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = (
        f"SELECT file_path, title, summary, ts_rank(body_tsv, q) AS rank, "
        f"  ts_headline('english', body, q, 'MaxWords=20, MinWords=10') AS snippet "
        f"FROM {TABLE_NAME}, plainto_tsquery('english', %s) q "
        f"WHERE body_tsv @@ q "
        f"ORDER BY rank DESC"
    )
    params = [query]
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    cur.execute(sql, params)
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def query_section(config, file_path, heading_text):
    """Extract a single section from a note by H2/H3 text. Requires Neon."""
    conn = get_connection(config)
    cur = conn.cursor()
    cur.execute(
        f"SELECT body FROM {TABLE_NAME} WHERE file_path = %s",
        (file_path,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        conn.close()
        return None
    body = row[0]

    cur.execute(
        f"SELECT level, position FROM {HEADINGS_TABLE_NAME} "
        f"WHERE file_path = %s ORDER BY position",
        (file_path,),
    )
    headings = cur.fetchall()
    conn.close()

    target_lower = heading_text.lower().strip()
    for i, (level, position) in enumerate(headings):
        line = body[position:body.index("\n", position) if "\n" in body[position:] else len(body)]
        clean = line.lstrip("#").strip().lower()
        if clean == target_lower or clean.startswith(target_lower):
            end = len(body)
            for j in range(i + 1, len(headings)):
                next_level, next_pos = headings[j]
                if next_level <= level:
                    end = next_pos
                    break
            return body[position:end].strip()
    return None


def query_dangling(config):
    """List all unresolved wikilinks. Requires Neon."""
    import psycopg2.extras
    conn = get_connection(config)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"SELECT source_path, target_path, link_type FROM {LINKS_TABLE_NAME} "
        f"WHERE target_resolved = false ORDER BY source_path, target_path"
    )
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def display_link_results(results, kind, as_json=False):
    if as_json:
        print(json.dumps(results, indent=2, default=json_serial))
        return
    if not results:
        print(f"No {kind} found.")
        return
    print(f"Found {len(results)} {kind}:\n")
    for r in results:
        if "source_path" in r and "target_path" in r:
            resolved = "" if r.get("target_resolved", True) else "  [DANGLING]"
            print(f"  {r.get('source_path','?')} -> {r.get('target_path','?')}  ({r['link_type']}){resolved}")
        elif "source_path" in r:
            print(f"  {r['source_path']}  ({r['link_type']})")
        elif "target_path" in r:
            resolved = "" if r.get("target_resolved", True) else "  [DANGLING]"
            print(f"  -> {r['target_path']}  ({r['link_type']}){resolved}")


def display_fts_results(results, as_json=False):
    if as_json:
        print(json.dumps(results, indent=2, default=json_serial))
        return
    if not results:
        print("No matches.")
        return
    print(f"Found {len(results)} match(es):\n")
    for r in results:
        print(f"  {r.get('title','(untitled)')}")
        print(f"    Path:    {r['file_path']}")
        print(f"    Rank:    {r.get('rank',0):.3f}")
        if r.get("summary"):
            print(f"    Summary: {r['summary']}")
        snippet = r.get("snippet", "")
        if snippet:
            print(f"    Snippet: {snippet}")
        print()


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
    # v1.4 graph + FTS commands (Neon required)
    parser.add_argument("--backlinks", metavar="PATH", help="List notes linking TO PATH")
    parser.add_argument("--forward-links", metavar="PATH", dest="forward_links",
                        help="List notes that PATH links TO")
    parser.add_argument("--search-fts", metavar="QUERY", dest="search_fts",
                        help="Full-text search across note bodies (Postgres tsvector)")
    parser.add_argument("--section", nargs=2, metavar=("PATH", "HEADING"),
                        help="Extract one section from a note by H2/H3 text")
    parser.add_argument("--dangling", action="store_true",
                        help="List all unresolved wikilinks (lint helper)")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.level:
        print_setup_level(config)
        return

    # v1.4 graph + FTS commands require Neon
    graph_commands = (args.backlinks, args.forward_links, args.search_fts,
                      args.section, args.dangling)
    if any(graph_commands):
        if not has_neon(config):
            print("  Graph and FTS queries require Neon (Level 3). "
                  "Add neon_connection_string to config.yaml.")
            sys.exit(1)
        if args.backlinks:
            display_link_results(query_backlinks(config, args.backlinks),
                                 "backlinks", args.json_output)
            return
        if args.forward_links:
            display_link_results(query_forward_links(config, args.forward_links),
                                 "forward links", args.json_output)
            return
        if args.search_fts:
            display_fts_results(query_fts(config, args.search_fts, args.limit),
                                args.json_output)
            return
        if args.section:
            section = query_section(config, args.section[0], args.section[1])
            if section is None:
                print(f"  No matching section found.")
                sys.exit(1)
            print(section)
            return
        if args.dangling:
            display_link_results(query_dangling(config), "dangling links",
                                 args.json_output)
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
