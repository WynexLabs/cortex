"""
Cortex Common — Shared utilities used by all Cortex scripts.

Handles config loading, frontmatter parsing, database connections,
validation, and the core upsert logic.

Cortex works progressively — it doesn't require all services to be configured.
The config tracks which layers are active:
  - vault_path: always required (just a folder of .md files)
  - git: optional (enables cross-machine file sync via GitHub)
  - neon_connection_string: optional (enables fast SQL queries)

Scripts check what's available and degrade gracefully.
"""

import yaml
import re
import subprocess
import json
from pathlib import Path
from datetime import date

TABLE_NAME = "cortex_notes"

# Allowed column types for schema extensions (whitelist)
ALLOWED_COLUMN_TYPES = {"TEXT", "INTEGER", "DATE", "BOOLEAN", "FLOAT", "TIMESTAMP"}

# type is fully open-ended — any string is accepted, no validation or auto-repair
# status and priority use a soft-validated set: unrecognised values produce a
# warning but are never auto-repaired or overwritten
VALID_STATUSES = {"active", "done", "ready", "planned", "draft", "waiting", "archived"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


def validate_identifier(name):
    """
    Validate that a string is a safe SQL identifier (column/table name).
    Only allows alphanumeric characters and underscores.
    """
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(
            f"Invalid identifier '{name}': must contain only letters, numbers, "
            f"and underscores, and start with a letter or underscore."
        )
    if len(name) > 63:
        raise ValueError(f"Identifier '{name}' exceeds max length of 63 characters.")
    return name


def validate_column_type(col_type):
    """Validate that a column type is in the allowed whitelist."""
    if col_type.upper() not in ALLOWED_COLUMN_TYPES:
        raise ValueError(
            f"Invalid column type '{col_type}'. "
            f"Allowed types: {', '.join(sorted(ALLOWED_COLUMN_TYPES))}"
        )
    return col_type.upper()


def validate_frontmatter(frontmatter, auto_repair=True):
    """
    Validate frontmatter fields and optionally auto-repair common issues.
    Returns (validated_frontmatter, warnings_list).
    """
    warnings = []
    fm = dict(frontmatter)

    # type is open-ended — any string value is accepted without validation

    if fm.get("status") and fm["status"] not in VALID_STATUSES:
        warnings.append(
            f"Unrecognised status '{fm['status']}' "
            f"(known: {', '.join(sorted(VALID_STATUSES))}); keeping as-is"
        )

    if fm.get("priority") and fm["priority"] not in VALID_PRIORITIES:
        warnings.append(
            f"Unrecognised priority '{fm['priority']}' "
            f"(known: {', '.join(sorted(VALID_PRIORITIES))}); keeping as-is"
        )

    today = date.today().isoformat()
    if not fm.get("created"):
        if auto_repair:
            fm["created"] = today
            warnings.append("Missing 'created' date, set to today")
        else:
            warnings.append("Missing 'created' date")

    if not fm.get("updated"):
        if auto_repair:
            fm["updated"] = today
            warnings.append("Missing 'updated' date, set to today")
        else:
            warnings.append("Missing 'updated' date")

    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
        warnings.append("Tags were a string, converted to list")
    if tags is None:
        tags = []
    tags = [t.lower().strip() for t in tags if t]
    fm["tags"] = tags

    return fm, warnings


def load_config(config_path):
    """
    Load and validate the .cortex/config.yaml file.
    Only vault_path is truly required — git and neon are optional layers.
    """
    config_path = Path(config_path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            f"Run 'python cortex_init.py' to set up, or create .cortex/config.yaml manually."
        )

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    if "vault_path" not in config:
        raise ValueError(
            "Missing required config key: 'vault_path'\n"
            "Your .cortex/config.yaml needs at least a 'vault_path'."
        )

    extensions = config.get("schema", {}).get("extensions", [])
    for ext in extensions:
        validate_identifier(ext["name"])
        if "type" in ext:
            validate_column_type(ext["type"])

    return config


def has_neon(config):
    """Check if Neon is configured."""
    conn_str = config.get("neon_connection_string", "")
    return bool(conn_str and conn_str.strip())


def has_git(config):
    """Check if the vault is a git repo."""
    vault_path = Path(config["vault_path"]).expanduser()
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=vault_path, capture_output=True
    )
    return result.returncode == 0


def get_setup_level(config):
    """
    Determine current setup level:
    0 = Just files (vault_path only)
    1 = + Obsidian (vault exists, .obsidian/ present)
    2 = + GitHub (git repo configured)
    3 = + Neon (database connected)
    """
    vault_path = Path(config["vault_path"]).expanduser()
    level = 0

    if (vault_path / ".obsidian").exists():
        level = 1

    if has_git(config):
        level = max(level, 2)

    if has_neon(config):
        level = 3

    return level


def print_setup_level(config):
    """Print current setup level and what's next."""
    level = get_setup_level(config)
    levels = [
        ("Files only", "Notes saved with structured frontmatter"),
        ("+ Obsidian", "Notes browsable and searchable locally"),
        ("+ GitHub", "Notes sync between machines via git"),
        ("+ Neon", "Fast SQL queries across your entire vault"),
    ]

    print(f"\n  Cortex setup level: {level}/3")
    for i, (name, desc) in enumerate(levels):
        marker = "✓" if i <= level else "○"
        print(f"    {marker} Level {i}: {name} — {desc}")

    if level < 3:
        next_name, next_desc = levels[level + 1]
        print(f"\n  Next upgrade: {next_name}")
        if level + 1 == 1:
            print("    → Point Obsidian at your vault folder")
        elif level + 1 == 2:
            print("    → git init && git remote add origin <your-repo-url>")
        elif level + 1 == 3:
            print("    → Add neon_connection_string to .cortex/config.yaml")
            print("    → Sign up free at https://neon.tech")


def get_connection(config):
    """Get a psycopg2 connection to Neon. Returns None if Neon isn't configured."""
    if not has_neon(config):
        return None

    import psycopg2
    conn_string = config["neon_connection_string"]
    if "sslmode" not in conn_string:
        conn_string += "?sslmode=require" if "?" not in conn_string else "&sslmode=require"
    return psycopg2.connect(conn_string)


def parse_frontmatter(file_path):
    """Parse YAML frontmatter from a markdown file. Returns dict or None."""
    file_path = Path(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return None

    try:
        fm = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(fm, dict):
        return None

    body = content[match.end():].strip()
    fm["_content_preview"] = body[:200] if body else ""
    fm["_body"] = body
    return fm


def find_md_files(vault_path):
    """Find all .md files in the vault, excluding hidden dirs and .cortex/."""
    vault_path = Path(vault_path)
    md_files = []
    for f in vault_path.rglob("*.md"):
        parts = f.relative_to(vault_path).parts
        if any(p.startswith(".") for p in parts):
            continue
        md_files.append(f)
    return sorted(md_files)


def upsert_note(conn, file_path, frontmatter, config):
    """
    Upsert a single note's frontmatter into Neon.
    All identifiers validated, all values parameterized.
    """
    import psycopg2.sql as sql_module

    vault_path = Path(config["vault_path"]).expanduser()
    rel_path = str(Path(file_path).relative_to(vault_path))

    fm, warnings = validate_frontmatter(frontmatter)
    for w in warnings:
        print(f"  Auto-repair ({Path(file_path).name}): {w}")

    columns = ["file_path", "title", "type", "status", "tags", "priority",
               "created", "updated", "content_preview"]

    extensions = config.get("schema", {}).get("extensions", [])
    for ext in extensions:
        columns.append(validate_identifier(ext["name"]))

    values = {
        "file_path": rel_path,
        "title": fm.get("title", Path(file_path).stem),
        "type": fm.get("type"),
        "status": fm.get("status"),
        "tags": fm.get("tags", []),
        "priority": fm.get("priority"),
        "created": fm.get("created", date.today().isoformat()),
        "updated": fm.get("updated", date.today().isoformat()),
        "content_preview": fm.get("_content_preview", ""),
    }

    for ext in extensions:
        values[ext["name"]] = fm.get(ext["name"], ext.get("default"))

    col_identifiers = [sql_module.Identifier(c) for c in columns]
    col_names = sql_module.SQL(", ").join(col_identifiers)
    placeholders = sql_module.SQL(", ").join(
        [sql_module.Placeholder(c) for c in columns]
    )
    updates = sql_module.SQL(", ").join([
        sql_module.SQL("{} = EXCLUDED.{}").format(
            sql_module.Identifier(c), sql_module.Identifier(c)
        )
        for c in columns if c != "file_path"
    ])

    query = sql_module.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(
        sql_module.Identifier(TABLE_NAME),
        col_names,
        placeholders,
        sql_module.Identifier("file_path"),
        updates,
    )

    cur = conn.cursor()
    cur.execute(query, values)


def local_query(vault_path, search=None, type_filter=None, status_filter=None,
                tag_filter=None, priority_filter=None, limit=None):
    """
    Query the vault by scanning .md files locally (no Neon required).
    Works at any setup level. Slower than SQL but always available.
    """
    vault_path = Path(vault_path).expanduser()
    md_files = find_md_files(vault_path)
    results = []

    for f in md_files:
        fm = parse_frontmatter(f)
        if not fm:
            continue

        fm_v, _ = validate_frontmatter(fm, auto_repair=False)
        rel_path = str(f.relative_to(vault_path))

        if type_filter and fm_v.get("type") != type_filter:
            continue
        if status_filter and fm_v.get("status") != status_filter:
            continue
        if priority_filter and fm_v.get("priority") != priority_filter:
            continue
        if tag_filter and tag_filter.lower() not in [t.lower() for t in fm_v.get("tags", [])]:
            continue
        if search:
            s = search.lower()
            searchable = " ".join([
                (fm_v.get("title") or ""),
                (fm_v.get("_content_preview") or ""),
                " ".join(fm_v.get("tags", [])),
            ]).lower()
            if s not in searchable:
                continue

        results.append({
            "file_path": rel_path,
            "title": fm_v.get("title", f.stem),
            "type": fm_v.get("type"),
            "status": fm_v.get("status"),
            "tags": fm_v.get("tags", []),
            "priority": fm_v.get("priority"),
            "created": fm_v.get("created"),
            "updated": fm_v.get("updated"),
            "content_preview": fm_v.get("_content_preview", ""),
        })

    results.sort(key=lambda r: r.get("updated") or "", reverse=True)
    if limit:
        results = results[:limit]
    return results


def git_commit_and_push(vault_path, files, config):
    """Commit and push if git is configured. No-op otherwise."""
    if not has_git(config):
        return

    git_config = config.get("git", {})
    if not git_config.get("auto_commit", False):
        return

    prefix = git_config.get("commit_prefix", "cortex:")
    remote = git_config.get("remote", "origin")
    branch = git_config.get("branch", "main")

    for f in files:
        subprocess.run(["git", "add", str(f)], cwd=vault_path, capture_output=True)

    if len(files) == 1:
        msg = f"{prefix} sync {files[0].stem}"
    else:
        msg = f"{prefix} sync {len(files)} files"

    result = subprocess.run(
        ["git", "commit", "-m", msg],
        capture_output=True, text=True, cwd=vault_path
    )
    if result.returncode != 0:
        if "nothing to commit" in (result.stdout or ""):
            return
        print(f"  Git commit failed: {result.stderr}")
        return

    print(f"  Git: {msg}")

    if git_config.get("auto_push", False):
        result = subprocess.run(
            ["git", "push", remote, branch],
            capture_output=True, text=True, cwd=vault_path
        )
        if result.returncode == 0:
            print(f"  Git: pushed to {remote}/{branch}")
        else:
            print(f"  Git: push failed — {result.stderr.strip()}")
