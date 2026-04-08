# Cortex Setup Guide

## What You Need

- Python 3.8+
- A GitHub account (free) — for syncing files between machines
- A Neon account (free tier) — for the query index. Sign up at https://neon.tech
- Git installed and configured on both your local machine and VPS
- An Obsidian vault (or any folder of .md files)

## Python Dependencies

Install on both machines:

```bash
pip install psycopg2-binary pyyaml
```

## Quick Start (2 minutes of your time, Claude Code does the rest)

### You do this:

1. **Create a GitHub repo** for your vault (or use an existing one). Private is fine.
2. **Sign up at neon.tech** and create a project. Copy the connection string:
   ```
   postgresql://username:password@ep-xxx-yyy.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

### Claude Code does this:

Tell Claude Code: "Set up Cortex for my vault at ~/notes with this Neon connection string: [paste it]"

Claude Code will:
1. Create `.cortex/config.yaml` with your settings
2. Add it to `.gitignore` (it contains your database password)
3. Create the Postgres table in Neon
4. Index all existing `.md` files
5. Verify with a test query
6. SSH into your VPS and set it up there too (same repo, same Neon database, VPS vault path)

## Manual Setup (if you prefer)

### Step 1: Create the Config File

In your vault root:

```bash
mkdir -p ~/notes/.cortex
```

Create `.cortex/config.yaml`:

```yaml
vault_path: ~/notes
neon_connection_string: postgresql://username:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require

git:
  auto_commit: true
  auto_push: true
  commit_prefix: "cortex:"
  remote: origin
  branch: main

schema:
  extensions: []
```

**Protect your credentials:**
```bash
echo ".cortex/config.yaml" >> .gitignore
```

### Step 2: Run Setup

```bash
python <cortex-skill-path>/scripts/cortex_setup.py --config ~/notes/.cortex/config.yaml
```

This creates the `cortex_notes` table and indexes all existing `.md` files.

### Step 3: Verify

```bash
python <cortex-skill-path>/scripts/cortex_query.py --config ~/notes/.cortex/config.yaml --status active
```

### Step 4: Set Up the VPS

On your VPS:

```bash
# Clone the same repo
git clone git@github.com:youruser/notes.git ~/notes

# Create the config (same Neon connection string, different vault_path if needed)
mkdir -p ~/notes/.cortex
cat > ~/notes/.cortex/config.yaml << 'EOF'
vault_path: ~/notes
neon_connection_string: postgresql://username:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require

git:
  auto_commit: true
  auto_push: true
  commit_prefix: "cortex:"
  remote: origin
  branch: main

schema:
  extensions: []
EOF

# Run setup (table already exists, so this just verifies + indexes)
python <cortex-skill-path>/scripts/cortex_setup.py --config ~/notes/.cortex/config.yaml
```

Both machines now share the same GitHub repo and the same Neon index.

## How Sync Works

```
Local Machine                    GitHub                     VPS (Open Claw)
     |                             |                             |
     |-- git push ----------------->|                             |
     |-- upsert to Neon ---------->|         (Neon DB)           |
     |                             |<------------- git pull -----|
     |                             |           upsert to Neon -->|
     |                             |                             |
     |  Both machines query Neon directly for fast lookups       |
```

The key: GitHub syncs files, Neon syncs metadata. Both are centrally accessible, both are free.

## Config Reference

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `vault_path` | Yes | — | Path to your .md vault on this machine |
| `neon_connection_string` | Yes | — | Neon Postgres connection URL |
| `git.auto_commit` | No | `false` | Auto-commit after file changes |
| `git.auto_push` | No | `false` | Auto-push after commits |
| `git.commit_prefix` | No | `cortex:` | Prefix for commit messages |
| `git.remote` | No | `origin` | Git remote name |
| `git.branch` | No | `main` | Git branch name |
| `schema.extensions` | No | `[]` | Additional frontmatter fields |

## Adding Custom Fields

1. Add to `schema.extensions`:
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

2. Run migration: `python cortex_migrate.py --config <config>`
3. Reindex: `python cortex_reindex.py --config <config>`

## Troubleshooting

**"Config not found"** — Run setup first, or create `.cortex/config.yaml` manually.

**"relation cortex_notes does not exist"** — The table hasn't been created. Run `cortex_setup.py` to create it. This usually means setup was skipped or failed partway through.

**Files not appearing in queries** — They need valid YAML frontmatter between `---` delimiters. Run `cortex_reindex.py --dry-run` to see which files would be indexed and which would be skipped.

**Git push fails** — Check that your VPS has git credentials configured (SSH key or credential helper). The sync script calls `git push` and relies on your existing auth setup.

**Connection refused to Neon** — Make sure `?sslmode=require` is at the end of your connection string. Neon requires SSL. The scripts enforce this automatically, but check your config if you're getting connection errors.

**"Invalid identifier" error** — Schema extension names can only contain letters, numbers, and underscores. Rename the field in your config.
