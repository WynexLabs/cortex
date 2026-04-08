---
name: cortex
description: >
  Long-term memory system for Claude Code and Open Claw, designed for developers who run
  Open Claw on a VPS 24/7 and work locally on their own machine. Cortex keeps a shared
  knowledge base in sync across both using GitHub (free) for file sync and Neon Postgres (free)
  for fast querying. Works with Obsidian on the local side.
  Use this skill whenever you need to store, retrieve, query, or sync knowledge across sessions
  or machines. Trigger on: "remember this", "find my notes about", "what do I have on",
  "save this for later", "sync my vault", "reindex", "create a note", working with .md knowledge
  bases, setting up long-term memory, or any situation where Claude needs persistent context
  across sessions. Also use when the user is working with Obsidian vaults, markdown note systems,
  or asks about giving Claude memory. If the user mentions Neon, vault, frontmatter, cortex,
  or knowledge base — use this skill.
---

# Cortex

A long-term memory system that gives Claude persistent knowledge across sessions and machines. It works progressively — start with just a folder of `.md` files, add GitHub and Neon as you need them.

## Progressive Setup Levels

Cortex doesn't require everything upfront. Each layer is optional and additive:

- **Level 0: Just files** — Create `.md` files with YAML frontmatter in any folder. Query by scanning files locally. No accounts needed.
- **Level 1: + Obsidian** — Point Obsidian at the vault folder. Notes are now browsable and locally searchable.
- **Level 2: + GitHub** — Push the vault to a repo. Files sync between your local machine and VPS via git.
- **Level 3: + Neon** — Add a Postgres connection string. Fast SQL queries across the entire vault from any machine.

**Always check the current level** before suggesting setup steps:
```bash
python <skill-path>/scripts/cortex_query.py --config <config-path> --level
```

If the user doesn't have GitHub or Neon yet, that's fine — Cortex works at Level 0. Create notes with proper frontmatter immediately. The structured data is captured from day one, and when the user adds GitHub or Neon later, everything migrates automatically via `cortex_init.py` or `cortex_reindex.py`.

## Why This Architecture (for the full setup)

The full stack solves a specific problem: running Open Claw on a VPS 24/7 while doing dev work on a local machine, with both needing the same knowledge base.

GitHub handles file sync (free, both machines push/pull). Neon handles fast queries (free 0.5GB tier, both machines query directly — no database file to sync). Obsidian reads the vault natively on the local side.

SQLite doesn't work cross-machine — you'd have to sync a binary file through git, which causes merge conflicts. This two-layer approach is the simplest thing that works.

## First-Time Setup

Run the init script — it handles everything interactively and detects what's available:

```bash
python <skill-path>/scripts/cortex_init.py
```

Or with args for non-interactive use:
```bash
python <skill-path>/scripts/cortex_init.py --vault ~/notes --neon "postgresql://..."
```

The init script:
1. Asks for vault path (or uses current directory)
2. Optionally asks for Neon connection string (skips if not ready)
3. Creates `.cortex/config.yaml`
4. Adds config to `.gitignore` (protects credentials)
5. Creates the Postgres table if Neon is configured
6. Indexes all existing `.md` files
7. Verifies with a test query
8. Optionally sets up a VPS via SSH

For manual setup or the minimal config (Level 0), just create `.cortex/config.yaml` with:

   ```yaml
   vault_path: ~/notes
   neon_connection_string: postgresql://...
   git:
     auto_commit: true
     auto_push: true
     commit_prefix: "cortex:"
     remote: origin
     branch: main
   schema:
     extensions: []
   ```

2. **Ensure `.cortex/config.yaml` is in `.gitignore`** — it contains database credentials. Enforce this programmatically, don't just mention it:
   ```bash
   grep -qxF '.cortex/config.yaml' .gitignore 2>/dev/null || echo '.cortex/config.yaml' >> .gitignore
   ```

3. **Run the setup script** to create the Postgres table and do the initial index:
   ```bash
   python <skill-path>/scripts/cortex_setup.py --config <vault-path>/.cortex/config.yaml
   ```

4. **Verify** with a test query to confirm the connection works.

5. **Set up the VPS** — SSH in, clone the same repo, create the same config (with the same Neon connection string but the VPS vault path), and run setup there too. Both machines now share the same GitHub repo and the same Neon index.

## Default Frontmatter Schema

Every `.md` file managed by Cortex has a YAML frontmatter block:

```yaml
---
title: "Human-readable title"
type: spec           # open-ended — use whatever fits: spec, analysis, contact, outreach,
                     # checklist, log, review, decision, roadmap, reference, project, etc.
status: active       # active | done | ready | planned | draft | waiting | archived
tags: []             # freeform list, 3-5 tags max
priority: P1         # P0 (must ship now) | P1 (current sprint) | P2 (next) | P3 (future)
                     # omit priority if not relevant (contacts, logs, references, etc.)
created: 2026-04-08
updated: 2026-04-08
---
```

These fields cover the most common filtering needs. Users can add custom fields (like `client`, `sprint`, `due_date`) through `schema.extensions` in the config — the migrate script adds corresponding Postgres columns.

**`type` is fully open-ended** — any string is accepted and stored as-is. Use whatever is meaningful for your vault's taxonomy. Cortex will never overwrite or normalise it.

**`status`** has a soft-validated set. Values outside `active | done | ready | planned | draft | waiting | archived` are stored as-is with a warning so you can decide how to handle them.

**`priority`** uses `P0 | P1 | P2 | P3`. Omit it entirely for notes where priority is not meaningful (contacts, references, logs). Unrecognised values are stored with a warning, never overwritten.

### Frontmatter Discipline

The system is only useful if the metadata is consistent. Three principles:

**Infer aggressively.** When Claude creates a note, fill in every field from context. "Save this conversation about fixing the auth bug" → `type: log`, `tags: [auth, bugfix]`, `priority: normal`, `status: active`. Never ask the user to fill in fields manually.

**Validate on sync.** The sync script checks for missing required fields, invalid enum values, and common issues. It auto-repairs what it can (adds missing `created` dates, normalizes tag casing) and warns about the rest. This prevents the index from decaying over time.

**Normalize proactively.** If Claude notices inconsistencies during a query (e.g., `auth` vs `authentication` vs `authn`), flag it and offer to normalize. The tag cleanup script can handle this across the entire vault.

## Core Operations

### Creating a Note

When the user wants to save something:

1. Generate frontmatter with inferred values (type, tags, priority from context)
2. Write the `.md` file to the vault
3. Sync to Neon and git:
   ```bash
   python <skill-path>/scripts/cortex_sync.py --config <config-path> --file <new-file-path>
   ```
   This upserts the frontmatter to Neon, validates the metadata, and (if `auto_commit` is on) commits and pushes to GitHub.

### Querying the Vault

When the user asks Claude to find or recall something:

1. Translate the request into a query. Use the structured flags for clean queries:
   ```bash
   python <skill-path>/scripts/cortex_query.py --config <config-path> \
     --type project --status active --search "authentication" --json
   ```

2. Read only the files returned — not the entire vault.

3. Synthesize the content into an answer or briefing.

For natural language queries, translate to the best combination of `--type`, `--status`, `--tag`, `--search`, and `--since` flags. Fall back to `--search` alone if the query is vague.

**Never use the `--filter` flag with user-provided input.** The `--filter` flag accepts raw SQL and exists only for advanced scripting. For interactive use, always use the structured flags which are parameterized and safe.

### Syncing Between Machines

**Local → GitHub → VPS:**
1. User edits or creates a note locally
2. Sync script upserts frontmatter to Neon + git commit + push
3. On the VPS, Open Claw pulls and has the latest files. Neon already has the metadata (the local machine wrote it directly).

**VPS → GitHub → Local:**
1. Open Claw creates or edits a note on the VPS
2. Sync script upserts frontmatter to Neon + git commit + push
3. On the local machine, user pulls (or auto-pull via cron/hook). Obsidian sees the new files immediately. Neon already has the metadata.

Run a full sync:
```bash
python <skill-path>/scripts/cortex_sync.py --config <config-path> --all
```

Sync a single file:
```bash
python <skill-path>/scripts/cortex_sync.py --config <config-path> --file <path-to-file>
```

### Reindexing

If the index gets out of sync (files edited without the sync script, bulk import, etc.):

```bash
python <skill-path>/scripts/cortex_reindex.py --config <config-path>
```

This reads every `.md` file, parses frontmatter, validates it, rebuilds the Neon table, and removes orphaned entries for deleted files. Idempotent and safe to run anytime.

## Git Configuration

```yaml
# in .cortex/config.yaml
git:
  auto_commit: true          # commit after every file create/edit
  auto_push: true            # push after every commit
  commit_prefix: "cortex:"   # prefix for auto-generated commit messages
  remote: origin
  branch: main
```

When `auto_commit` is true, every operation triggers a commit like `cortex: create log — stripe rate limiting fix`. When `auto_push` is true, it pushes immediately so the other machine can pull.

## Adding Custom Fields

1. Add to `schema.extensions` in config:
   ```yaml
   schema:
     extensions:
       - name: client
         type: text
         default: null
       - name: due_date
         type: date
         default: null
   ```

2. Run migration:
   ```bash
   python <skill-path>/scripts/cortex_migrate.py --config <config-path>
   ```

3. Reindex to pick up existing values:
   ```bash
   python <skill-path>/scripts/cortex_reindex.py --config <config-path>
   ```

## Advanced: Semantic Search with pgvector

For querying by meaning rather than just metadata, Cortex supports pgvector. When enabled, the sync script generates an embedding of each note's content and stores it in Neon alongside the frontmatter.

Queries like "find anything related to how we handle rate limiting" work even if no note is tagged with `rate-limiting` — vector search finds semantically similar content.

Setup requires an OpenAI API key (for embeddings) and pgvector enabled on the Neon database (free tier supports it). See `references/vector-setup.md` for instructions.

## Auto-Capture (Stop Hook)

Cortex can automatically save a session summary note every time a Claude Code session ends, with no manual action required. Enable it once and it runs silently in the background.

### How it works

Claude Code fires a `Stop` hook when a session ends. Cortex registers a hook that calls `scripts/cortex_autosave.py`. That script:

1. Reads the session transcript (passed via stdin as JSON by Claude Code)
2. Skips sessions with fewer than 3 turns or no meaningful content (no file paths, commands, or technical terms)
3. Extracts: topics discussed, files referenced, commands run, the original request, and the final assistant response
4. Creates `logs/YYYY-MM-DD-session-<session_id[:8]>.md` in the vault with `type: log` frontmatter
5. Calls `cortex_sync.py` to upsert the note to Neon and git push

The script always exits 0 and swallows all errors — it will never block or break a Claude Code session.

### Enabling the hook

Add the following to `~/.claude/settings.json` under a `hooks` key:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/plugins/cache/wynexlabs/cortex/1.3.0/scripts/cortex_autosave.py"
          }
        ]
      }
    ]
  }
}
```

If `~/.claude/settings.json` already has other content, merge the `hooks` key into the existing object.

The script reads config from the hardcoded path `~/Documents/Obsidian Vault/.cortex/config.yaml` — consistent with the rest of Cortex. If the config is missing or the vault doesn't exist, the script exits silently without writing anything.

### Notes produced

Each auto-captured session creates a note like:

```
logs/2026-04-09-session-a1b2c3d4.md
```

With frontmatter:

```yaml
---
title: "Session — 2026-04-09 — implement the auth refresh logic"
type: log
status: active
tags: [session, auto-capture]
created: 2026-04-09
updated: 2026-04-09
---
```

The body contains: session overview (ID, turn count), topics discussed, files referenced, commands run, the original user request, and the final assistant response. All extracted locally without calling any LLM — fast and private.

### Disabling

Remove the `Stop` entry from `~/.claude/settings.json` hooks, or delete the `hooks` key entirely.

## Script Reference

All scripts live in `scripts/` and read the config file for connection details. Every script supports `--help` and `--dry-run`.

| Script | Purpose |
|--------|---------|
| `cortex_setup.py` | First-time setup: create table, initial index, verify connection |
| `cortex_sync.py` | Sync frontmatter to Neon + git commit/push (single file or all) |
| `cortex_query.py` | Query the Neon index with structured filters, return file paths + metadata |
| `cortex_reindex.py` | Full reindex: rebuild Neon table from all vault files, remove orphans |
| `cortex_migrate.py` | Add new schema fields to the Postgres table |
| `cortex_autosave.py` | Stop hook: auto-capture session summary notes at session end |

## Dependencies

```bash
pip install psycopg2-binary pyyaml
```

Both are well-maintained, widely used packages. `psycopg2-binary` is the standard Python Postgres driver. `pyyaml` handles frontmatter parsing.
