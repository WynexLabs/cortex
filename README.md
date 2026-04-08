# Cortex

Long-term memory for Claude Code and Open Claw, across machines.

---

If you run Open Claw on a VPS for 24/7 availability but do your dev work on a local machine, you've hit this problem: AI doesn't remember anything between sessions, and your knowledge is stuck on whichever machine you wrote it on.

Cortex fixes this with two free services you probably already use:

- **GitHub** syncs your markdown files between machines (source of truth)
- **Neon Postgres** indexes the metadata so Claude can query your vault fast without scanning every file

On your local machine, the vault is just a folder of `.md` files — Obsidian reads it natively. On your VPS, Open Claw reads and writes the same files. Both machines push/pull through GitHub, both query the same Neon database.

```
Local Machine ←── GitHub ──→ VPS (Open Claw)
       ↕                           ↕
       └────── Neon Postgres ──────┘
               (shared index)
```

## How it works

Every markdown file has YAML frontmatter — structured metadata at the top:

```yaml
---
title: "Stripe rate limiting fix"
type: log
status: active
tags: [payments, stripe, bugfix]
priority: high
created: 2026-04-08
updated: 2026-04-08
---

We were hitting 429s on the Stripe API because our retry logic
wasn't backing off properly. Fixed with exponential backoff + jitter.
```

Cortex indexes these fields in Neon so Claude can query them: "find all active project notes tagged with deployment" returns file paths in milliseconds, then Claude reads only those files.

## Install (one-liner)

Paste this into your terminal:

```bash
curl -sL https://raw.githubusercontent.com/wynexlabs/cortex/main/install.sh | bash
```

Or clone manually:

```bash
git clone https://github.com/wynexlabs/cortex.git ~/.claude/skills/cortex
```

Then run init:

```bash
python3 ~/.claude/skills/cortex/scripts/cortex_init.py
```

Or just tell Claude: *"Set up Cortex for my vault"* — it handles the rest.

## Progressive setup — start now, add layers later

Cortex doesn't require everything upfront. It works immediately with just a folder, and each service you add unlocks more capability. Your notes are structured from day one — nothing is wasted.

```
Level 0: Just files      → Notes saved with structured frontmatter
Level 1: + Obsidian      → Notes browsable and searchable locally
Level 2: + GitHub        → Notes sync between machines via git
Level 3: + Neon          → Fast SQL queries across your entire vault
```

**Start at Level 0** — just tell Claude *"Save a note about..."* and it creates a `.md` file with proper YAML frontmatter. No accounts needed.

**Add Obsidian** whenever you want — point it at your vault folder and your notes are instantly browsable with full search.

**Add GitHub** when you need cross-machine sync — `git init`, push to a repo, and your VPS can pull the same files. Open Claw pushes, you pull. Free.

**Add Neon** when your vault grows and you want fast structured queries — sign up at [neon.tech](https://neon.tech) (free), paste the connection string into your config, and run `cortex_init.py`. Every note you've already written gets indexed automatically.

Each step is optional. Each step preserves everything from before. See [references/setup-guide.md](references/setup-guide.md) for the full walkthrough.

## What you can do

**Save knowledge:**

> "Save a note about how we fixed the auth bug — the session tokens were expiring because the refresh logic had a race condition"

Claude creates a `.md` file with inferred frontmatter, syncs to Neon, and pushes to GitHub.

**Query across sessions:**

> "What do I have about our deployment pipeline?"

Claude queries Neon, finds matching notes, reads only those files, and gives you a summary.

**Pre-load context:**

> "I'm about to refactor notifications. Pull up everything I've written about the notification system."

Claude searches your vault and builds a briefing before you start.

**Sync between machines:**

> "Sync my vault"

Pulls latest from GitHub, reindexes to Neon. Works from either machine.

**Clean up:**

> "Some of my tags are inconsistent — auth vs authentication vs authn. Help me normalize them."

Claude queries the index, proposes a mapping, and normalizes across your entire vault.

## Architecture

```
┌─────────────────────────────────────────────┐
│                 Your Vault                   │
│  .md files with YAML frontmatter            │
│  (Obsidian-compatible)                       │
├──────────────────┬──────────────────────────┤
│   GitHub Repo    │    Neon Postgres          │
│   (file sync)    │    (query index)          │
│                  │                           │
│   Source of      │    Mirrors frontmatter    │
│   truth for      │    fields + file paths    │
│   content        │    for fast SQL queries   │
├──────────────────┴──────────────────────────┤
│              Both machines                   │
│   Local: Obsidian + Claude Code              │
│   VPS:   Open Claw (24/7)                    │
│   Both push/pull GitHub, both query Neon     │
└─────────────────────────────────────────────┘
```

## Scripts

| Script | What it does |
|--------|-------------|
| `cortex_setup.py` | First-time setup — creates the Postgres table, indexes existing files |
| `cortex_sync.py` | Syncs frontmatter to Neon + git commit/push |
| `cortex_query.py` | Queries the index with structured filters |
| `cortex_reindex.py` | Full rebuild of the index from disk |
| `cortex_migrate.py` | Adds new columns when you extend the schema |

All scripts support `--help` and `--dry-run`.

## Default frontmatter schema

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `title` | text | filename | Human-readable name |
| `type` | enum | `note` | `note`, `project`, `prompt`, `reference`, `log` |
| `status` | enum | `active` | `active`, `archived`, `draft` |
| `tags` | list | `[]` | Freeform, 3-5 per note |
| `priority` | enum | `normal` | `low`, `normal`, `high`, `critical` |
| `created` | date | today | When it was created |
| `updated` | date | today | Last modified |

Add custom fields (like `client`, `due_date`, `sprint`) through the config. See [setup guide](references/setup-guide.md#adding-custom-fields).

## Advanced: semantic search

Cortex optionally supports pgvector for querying by meaning, not just metadata. "Find anything about rate limiting" works even if no note is tagged `rate-limiting`. Requires an OpenAI API key for embeddings. Neon's free tier supports pgvector.

## License

MIT — use it however you want.
