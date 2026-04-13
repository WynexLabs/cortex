# Cortex — AI-Prioritized Vault Toolchain for Claude Code

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/WynexLabs/cortex)](https://github.com/WynexLabs/cortex/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-blueviolet)](https://github.com/topics/claude-code-plugin)

> A Markdown vault optimized for LLM consumption — graph-aware, full-text searchable, semantic when you need it. Works progressively: start with files, add layers as you grow.

---

## What it solves

Three problems every AI-coding workflow eventually hits:

1. **Your AI has no memory between sessions.** Every conversation starts from zero.
2. **Your knowledge is unstructured prose.** Loading the right context burns tokens you didn't budget for.
3. **You can't search your own notes the way an LLM needs to.** Filename grep doesn't cut it; semantic search alone misses structure.

Cortex turns a plain Markdown folder into a graph-aware, full-text-searchable, optionally-semantic knowledge base that an LLM can query precisely — by tag, by link graph, by full text, by section, by similarity. Conventions plus a lint script keep notes clean as the vault grows.

## How it works (30 seconds)

Notes are Markdown files with YAML frontmatter:

```yaml
---
type: log
status: active
summary: One-sentence TLDR so the LLM can decide whether to load the rest.
tags: [payments, stripe, bugfix]
created: 2026-04-13
updated: 2026-04-13
---

# Stripe rate limiting fix

Brief problem description, [[stripe-integration]] context, and the resolution.
```

Cortex parses these into a Postgres index that an LLM can query in milliseconds:
- `--search-fts "rate limiting"` — full-text search across all bodies
- `--backlinks projects/strata/README.md` — what references this note
- `--section infrastructure/vps.md "Identity"` — pull just one section
- `--type spec --status active` — filter by structured metadata

The LLM reads only the files it needs, in the right slices. You get cross-session memory and your tokens stay under control.

## Setup matrix — pick your recipe

Cortex works at every layer. Each row is a valid configuration:

| Setup | Files + Obsidian | + GitHub | + Neon | + Embeddings |
|---|:---:|:---:|:---:|:---:|
| **Solo dev, no cloud** | ✓ | | | |
| **Solo dev with sync** | ✓ | ✓ | | |
| **Solo dev with fast queries** | ✓ | | ✓ | |
| **Multi-machine setup with VPS** | ✓ | ✓ | ✓ | optional |
| **Full power (semantic search)** | ✓ | ✓ | ✓ | ✓ |

Capabilities by level:

| Level | What you add | What unlocks |
|---|---|---|
| 0 | Just `.md` files | Local file-scan queries; structured frontmatter from day one |
| 1 | + Obsidian | Native UI browsing, instant local search |
| 2 | + GitHub | Cross-machine sync (laptop ↔ VPS, work ↔ home) |
| 3 | + Neon Postgres | Fast SQL queries, **wikilink graph traversal**, **full-text search**, **section addressing** |
| 4 | + Embeddings (pgvector) | Semantic search — "find anything about auth" even without that tag |

You can stop at any level. Going up later costs nothing — your existing notes get indexed automatically.

## Quick start (Level 0 — just files)

```bash
curl -sL https://raw.githubusercontent.com/wynexlabs/cortex/main/install.sh | bash
```

Installs the Cortex Claude Code plugin. Then in Claude Code:

> *"Set up Cortex for my vault."*

That's it. Claude creates `.cortex/config.yaml`, walks you through whatever level fits, and starts saving notes with proper frontmatter.

## Progressive setup

### Level 0 → 1: Add Obsidian

Point [Obsidian](https://obsidian.md) at your vault folder. Notes become browsable with backlinks and a graph view. Free.

### Level 1 → 2: Add GitHub

```bash
cd ~/your-vault
git init && git remote add origin git@github.com:you/your-vault.git
```

Cortex auto-commits and pushes (configurable). Multi-machine sync without conflict drama.

### Level 2 → 3: Add Neon

Sign up at [neon.tech](https://neon.tech) (free tier covers most personal use), copy the connection string into `.cortex/config.yaml`, and run:

```bash
python scripts/cortex_migrate.py --config .cortex/config.yaml
python scripts/cortex_reindex.py --config .cortex/config.yaml
```

Schema migrates additively. All your existing notes get indexed.

### Level 3 → 4: Add embeddings (semantic search)

Set an `embedding_provider` and API key in your config. Run reindex once to embed the vault. Queries via `--semantic-search` find notes by meaning, not just keywords. Coming in v1.5.

## Use cases

### Solo developer, single machine

Just files plus Obsidian. Cortex saves notes with structured frontmatter. Claude reads the right files instead of the whole vault. No cloud required.

### Multi-machine setup with VPS

Files + GitHub + Neon. Same notes on your laptop and your VPS, both querying the same Neon index. Push from one, pull from the other.

### Open Claw on VPS + local dev

The original Cortex use case. Run [Open Claw](https://github.com/topics/openclaw) on a VPS for 24/7 availability while you do dev work locally. Both reach the same vault.

```
Local Machine  ←──  GitHub  ──→  VPS (Open Claw)
       ↕                                ↕
       └─────────  Neon Postgres  ──────┘
                  (shared index)
```

### CI / agent workflows

Cortex's CLI is scriptable. Lint as a CI gate, query in pre-commit hooks, bundle context for agent runs. See the [setup guide](references/setup-guide.md).

## Conventions

A vault built for LLMs benefits from a writing standard. Cortex ships with [10 LLM-first conventions](references/setup-guide.md#conventions) covering required frontmatter (`summary:`, `aliases:`, `see-also:`), atomic note size, wikilink rules, and pronoun avoidance at section openers.

The `cortex_lint.py` script enforces 7 of the 10 mechanically — never modifies files, never blocks indexing, just surfaces warnings:

```bash
python scripts/cortex_lint.py --config .cortex/config.yaml
```

The other 3 conventions need human judgment and are documented for self-application.

## Auto-capture (Stop hook)

Cortex can silently log every Claude Code session as a `type: log` note. Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/plugins/cache/wynexlabs/cortex/1.4.0/scripts/cortex_autosave.py"
      }]
    }]
  }
}
```

Reads the transcript, skips trivial sessions, captures topics/files/commands. Always exits 0 — never blocks Claude Code.

## Architecture

```
┌─────────────────────────────────────────────┐
│              Your Markdown Vault             │
│   .md files with YAML frontmatter           │
│   (Obsidian-compatible)                      │
├──────────────────┬──────────────────────────┤
│   GitHub Repo    │    Neon Postgres          │
│   (file sync)    │    (query index)          │
│                  │                           │
│   Source of      │  cortex_notes (metadata,  │
│   truth          │  body, FTS tsvector)      │
│                  │  cortex_links (graph)     │
│                  │  cortex_headings (anchors)│
│                  │  cortex_embeddings (v1.5) │
├──────────────────┴──────────────────────────┤
│              Any number of machines          │
│   Each pushes/pulls GitHub, queries Neon     │
└─────────────────────────────────────────────┘
```

## Scripts

| Script | What it does |
|--------|-------------|
| `cortex_init.py` | Interactive first-time setup |
| `cortex_setup.py` | Programmatic setup — creates tables, indexes existing files |
| `cortex_sync.py` | Sync changes to Neon + git commit/push |
| `cortex_query.py` | Query the index — search, filter, graph, FTS, sections |
| `cortex_reindex.py` | Full rebuild from disk (idempotent) |
| `cortex_migrate.py` | Apply schema migrations (core + user extensions) |
| `cortex_lint.py` | Lint vault against the 10 LLM-first conventions |
| `cortex_autosave.py` | Stop hook — auto-captures sessions |

All scripts support `--help` and `--dry-run` where applicable.

## Default frontmatter schema

| Field | Values | Purpose |
|-------|--------|---------|
| `summary` | 1–3 sentences | **TLDR — the highest-leverage field for LLM consumption** |
| `title` | string | Human-readable name (defaults to filename) |
| `type` | string | Open-ended — `log`, `spec`, `decision`, `reference`, `project`, etc. |
| `aliases` | list | Disambiguation — `["Strata", "project-strata", "strata-app"]` |
| `see-also` | list | Explicit related-notes pointers |
| `status` | `active` \| `done` \| `ready` \| `planned` \| `draft` \| `waiting` \| `archived` | Lifecycle state |
| `supersedes` | wikilink | Marks this note as replacing another (auto-archives target) |
| `source` | string | Citation for non-obvious facts |
| `tags` | list | Freeform |
| `priority` | `P0`–`P3` | Optional |
| `created` / `updated` | date | ISO 8601 |

Custom fields via `schema.extensions` in config. See the [setup guide](references/setup-guide.md#adding-custom-fields).

## How Cortex compares

| | Cortex | CLAUDE.md | claude-mem | total-recall |
|---|---|---|---|---|
| Wikilink graph traversal | ✓ | — | — | — |
| Full-text search | ✓ (Postgres tsvector) | — | — | — |
| Section-level addressing | ✓ | — | — | — |
| Cross-machine sync | ✓ (GitHub) | — | — | — |
| Structured metadata | YAML frontmatter | Freeform | Compressed blobs | Tiered text |
| Obsidian-compatible | Native | No | No | No |
| Semantic search | ✓ (v1.5, pgvector) | No | ✓ | No |
| Lint script for conventions | ✓ | — | — | — |
| Zero-dependency start | Level 0 (just files) | Yes | No | No |

## License

MIT — use it however you want.
