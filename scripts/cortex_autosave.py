#!/usr/bin/env python3
"""
Cortex Autosave — Auto-capture hook for Claude Code sessions.

Called automatically by the Claude Code Stop hook when a session ends.
Reads the session transcript, extracts meaningful content, and saves a
log note to the vault if the session had substance.

Hook input arrives on stdin as JSON:
    {
        "session_id": "...",
        "transcript_path": "/path/to/transcript.jsonl",
        "stop_hook_active": true
    }

This script ALWAYS exits 0 — it must never block or break Claude Code.
"""

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


# --- Constants ---------------------------------------------------------------

CONFIG_PATH = Path("~/Documents/Obsidian Vault/.cortex/config.yaml").expanduser()
SCRIPTS_DIR = Path(__file__).parent

# Minimum turns needed to consider a session worth saving.
# A "turn" = one user message + one assistant message.
MIN_TURNS = 3

# How many of the most recent turns to inspect for summary material.
SUMMARY_WINDOW = 20

# Patterns that suggest a message is substantive (not just small talk).
# We count how many lines/messages match these — if none match across the
# whole session we skip saving.
SUBSTANCE_PATTERNS = [
    r"\bfile\b", r"\bpath\b", r"\.py\b", r"\.ts\b", r"\.js\b", r"\.md\b",
    r"\bfunction\b", r"\bclass\b", r"\bscript\b", r"\bcommand\b",
    r"\bconfig\b", r"\bsetup\b", r"\binstall\b", r"\bdeploy\b",
    r"\bbug\b", r"\bfix\b", r"\berror\b", r"\bissue\b", r"\bproblem\b",
    r"\bimplemented?\b", r"\bcreated?\b", r"\bupdated?\b", r"\bchanged?\b",
    r"\bbuilt?\b", r"\bwritten?\b", r"\brefactor\b", r"\bmigrat\b",
    r"\btest\b", r"\bdebug\b", r"\bdatabase\b", r"\bapi\b", r"\bauth\b",
    r"\bproject\b", r"\btask\b", r"\bfeature\b", r"\brelease\b",
    r"\bneon\b", r"\bprisma\b", r"\bgit\b", r"\bgithub\b", r"\bpush\b",
]
SUBSTANCE_RE = re.compile("|".join(SUBSTANCE_PATTERNS), re.IGNORECASE)

# Patterns used to extract specific artefacts from transcript text.
FILE_PATH_RE = re.compile(
    r"(?:^|[\s`'\"])(/[\w./\-]+\.(?:py|ts|tsx|js|jsx|md|yaml|yml|json|sh|sql))"
)
COMMAND_RE = re.compile(r"```(?:bash|sh|zsh)\s*\n(.*?)```", re.DOTALL)
TOPIC_WORDS_RE = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b")  # Title-cased phrases


# --- Transcript helpers -------------------------------------------------------

def read_transcript(transcript_path: str) -> list[dict]:
    """Read a .jsonl transcript file. Returns list of {role, content} dicts."""
    path = Path(transcript_path)
    if not path.exists():
        return []

    turns = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                role = obj.get("role", "")
                content = obj.get("content", "")

                # content may be a list of content blocks (Claude API format)
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = " ".join(text_parts)

                if role and isinstance(content, str) and content.strip():
                    turns.append({"role": role, "content": content.strip()})
    except Exception:
        return []

    return turns


def count_turns(turns: list[dict]) -> int:
    """Count user+assistant turn pairs."""
    user_count = sum(1 for t in turns if t["role"] == "user")
    asst_count = sum(1 for t in turns if t["role"] == "assistant")
    return min(user_count, asst_count)


def is_substantive(turns: list[dict]) -> bool:
    """Return True if the transcript contains meaningful technical content."""
    combined = " ".join(t["content"] for t in turns)
    return bool(SUBSTANCE_RE.search(combined))


# --- Summary extraction -------------------------------------------------------

def extract_file_paths(text: str) -> list[str]:
    """Extract file paths mentioned in the text."""
    paths = FILE_PATH_RE.findall(text)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:10]  # cap at 10


def extract_commands(text: str) -> list[str]:
    """Extract bash commands from code fences."""
    matches = COMMAND_RE.findall(text)
    commands = []
    for block in matches:
        for line in block.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 3:
                commands.append(line)
    return commands[:8]  # cap at 8


def extract_topics(turns: list[dict]) -> list[str]:
    """Extract topic keywords from the first few user messages."""
    # Use the first 5 user messages as they usually state the goal
    user_messages = [t["content"] for t in turns if t["role"] == "user"][:5]
    combined = " ".join(user_messages)

    # Pull out noun phrases and technical keywords
    topics = set()

    # Title-cased multi-word phrases (project names, feature names, etc.)
    for phrase in TOPIC_WORDS_RE.findall(combined):
        if len(phrase) > 4:
            topics.add(phrase)

    # Common technical keywords that appear frequently
    tech_keywords = re.findall(
        r"\b(auth(?:entication)?|deploy(?:ment)?|migration?|refactor|database|"
        r"API|webhook|stripe|neon|prisma|docker|ci/cd|test(?:ing)?|"
        r"bug\s*fix|setup|install|scaffold|hook)\b",
        combined,
        re.IGNORECASE,
    )
    for kw in tech_keywords:
        topics.add(kw.lower())

    return sorted(topics)[:8]


def build_one_liner(turns: list[dict]) -> str:
    """
    Produce a single-line summary of what the session was about.
    Looks at the first user message and last assistant message for signals.
    """
    user_messages = [t["content"] for t in turns if t["role"] == "user"]
    asst_messages = [t["content"] for t in turns if t["role"] == "assistant"]

    first_user = user_messages[0] if user_messages else ""
    last_asst = asst_messages[-1] if asst_messages else ""

    # Truncate long messages to avoid noise
    first_user = first_user[:300].replace("\n", " ")
    last_asst = last_asst[:200].replace("\n", " ")

    # Try to extract the core intent from the first user message
    # Strip common filler phrases
    clean = re.sub(
        r"^(?:hey|hi|hello|please|can you|could you|i need|i want|i'd like|help me|"
        r"let's|let me|we need|we want|we should|make sure|ensure)[,\s]*",
        "",
        first_user,
        flags=re.IGNORECASE,
    ).strip()

    # Take the first sentence
    sentence_end = re.search(r"[.!?]", clean)
    if sentence_end and sentence_end.start() > 10:
        clean = clean[: sentence_end.start()].strip()

    # Fallback: if we got very little, use a generic description
    if len(clean) < 8:
        clean = "coding session"

    # Cap at ~80 chars for the title
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "..."

    return clean


def build_summary_body(
    turns: list[dict],
    session_id: str,
    transcript_path: str,
) -> str:
    """Build the markdown body of the session log note."""
    recent_turns = turns[-SUMMARY_WINDOW:]
    combined_text = " ".join(t["content"] for t in recent_turns)
    all_text = " ".join(t["content"] for t in turns)

    file_paths = extract_file_paths(all_text)
    commands = extract_commands(all_text)
    topics = extract_topics(turns)

    user_messages = [t["content"] for t in turns if t["role"] == "user"]
    asst_messages = [t["content"] for t in turns if t["role"] == "assistant"]
    total_turns = count_turns(turns)

    lines = []

    # Session overview
    lines.append("## Session overview")
    lines.append("")
    lines.append(f"- **Session ID**: `{session_id}`")
    lines.append(f"- **Turns**: {total_turns}")
    lines.append(f"- **Transcript**: `{transcript_path}`")
    lines.append("")

    # Topics/keywords
    if topics:
        lines.append("## Topics discussed")
        lines.append("")
        for t in topics:
            lines.append(f"- {t}")
        lines.append("")

    # Files touched
    if file_paths:
        lines.append("## Files referenced")
        lines.append("")
        for fp in file_paths:
            lines.append(f"- `{fp}`")
        lines.append("")

    # Commands run
    if commands:
        lines.append("## Commands / operations")
        lines.append("")
        lines.append("```bash")
        for cmd in commands[:5]:
            lines.append(cmd)
        lines.append("```")
        lines.append("")

    # First user message (the original ask)
    if user_messages:
        lines.append("## Original request")
        lines.append("")
        first = user_messages[0][:500].replace("\n", "\n> ")
        lines.append(f"> {first}")
        lines.append("")

    # Last assistant message snippet (outcome summary)
    if asst_messages:
        lines.append("## Outcome (last assistant message)")
        lines.append("")
        last = asst_messages[-1][:600].replace("\n", "\n> ")
        lines.append(f"> {last}")
        lines.append("")

    return "\n".join(lines)


# --- Config loading -----------------------------------------------------------

def load_config_yaml(config_path: Path) -> dict:
    """Load the .cortex/config.yaml. Returns {} on any error."""
    try:
        import yaml  # type: ignore
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        if not isinstance(cfg, dict):
            return {}
        return cfg
    except Exception:
        return {}


# --- Note writing -------------------------------------------------------------

def write_note(vault_path: Path, session_id: str, one_liner: str, body: str) -> Path:
    """Write the log .md file and return its path."""
    today = date.today().isoformat()
    short_id = session_id[:8] if len(session_id) >= 8 else session_id
    filename = f"{today}-session-{short_id}.md"

    logs_dir = vault_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    note_path = logs_dir / filename

    title = f"Session — {today} — {one_liner}"
    tags_yaml = "[session, auto-capture]"

    frontmatter = f"""---
title: "{title}"
type: log
status: active
tags: {tags_yaml}
created: {today}
updated: {today}
---

"""

    note_path.write_text(frontmatter + body, encoding="utf-8")
    return note_path


def call_cortex_sync(config_path: Path, note_path: Path) -> None:
    """Call cortex_sync.py to upsert the note to Neon and git push."""
    sync_script = SCRIPTS_DIR / "cortex_sync.py"
    if not sync_script.exists():
        return

    subprocess.run(
        [sys.executable, str(sync_script),
         "--config", str(config_path),
         "--file", str(note_path)],
        capture_output=True,
        timeout=60,
    )


# --- Main entry point ---------------------------------------------------------

def main() -> int:
    """Main function. Always returns 0 — never raises."""
    try:
        # Read hook context from stdin
        raw_stdin = sys.stdin.read().strip()
        if not raw_stdin:
            return 0

        try:
            hook_ctx = json.loads(raw_stdin)
        except json.JSONDecodeError:
            return 0

        session_id = hook_ctx.get("session_id", "unknown")
        transcript_path = hook_ctx.get("transcript_path", "")

        if not transcript_path:
            return 0

        # Read and parse the transcript
        turns = read_transcript(transcript_path)
        if not turns:
            return 0

        # Skip trivial sessions
        n_turns = count_turns(turns)
        if n_turns < MIN_TURNS:
            return 0

        if not is_substantive(turns):
            return 0

        # Load Cortex config
        config = load_config_yaml(CONFIG_PATH)
        if not config:
            # Config not found or unreadable — skip silently
            return 0

        vault_path_raw = config.get("vault_path", "")
        if not vault_path_raw:
            return 0

        vault_path = Path(vault_path_raw).expanduser()
        if not vault_path.exists():
            return 0

        # Build summary
        recent = turns[-SUMMARY_WINDOW:]
        one_liner = build_one_liner(turns)
        body = build_summary_body(turns, session_id, transcript_path)

        # Write note
        note_path = write_note(vault_path, session_id, one_liner, body)

        # Sync to Neon + git
        call_cortex_sync(CONFIG_PATH, note_path)

    except Exception:
        # Swallow all errors — never break Claude Code
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
