#!/bin/bash
# Cortex Installer — One-liner for Claude Code
#
# Usage (copy-paste into your terminal):
#   curl -sL https://raw.githubusercontent.com/wynexlabs/cortex/main/install.sh | bash
#
# Or if you prefer to inspect before running:
#   curl -sL https://raw.githubusercontent.com/wynexlabs/cortex/main/install.sh -o install.sh
#   cat install.sh
#   bash install.sh

set -e

REPO="https://github.com/wynexlabs/cortex.git"
SKILL_DIR="${HOME}/.claude/skills/cortex"

echo ""
echo "  ╔═══════════════════════════════════╗"
echo "  ║      Installing Cortex            ║"
echo "  ║   Long-term memory for Claude     ║"
echo "  ╚═══════════════════════════════════╝"
echo ""

# Check for git
if ! command -v git &> /dev/null; then
    echo "  ✗ git is required. Install it first."
    exit 1
fi

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo "  ✗ python3 is required. Install it first."
    exit 1
fi

# Create skills directory if needed
mkdir -p "${HOME}/.claude/skills"

# Clone or update
if [ -d "$SKILL_DIR" ]; then
    echo "  Updating existing installation..."
    cd "$SKILL_DIR"
    git pull --quiet
    echo "  ✓ Updated to latest version"
else
    echo "  Cloning Cortex..."
    git clone --quiet "$REPO" "$SKILL_DIR"
    echo "  ✓ Installed to $SKILL_DIR"
fi

# Install Python dependencies
echo "  Installing Python dependencies..."
pip install psycopg2-binary pyyaml --break-system-packages --quiet 2>/dev/null || \
pip install psycopg2-binary pyyaml --quiet 2>/dev/null || \
echo "  ⚠ Could not auto-install dependencies. Run: pip install psycopg2-binary pyyaml"

echo ""
echo "  ✓ Cortex installed!"
echo ""
echo "  Next step — run init in Claude Code:"
echo "    python3 ${SKILL_DIR}/scripts/cortex_init.py"
echo ""
echo "  Or just tell Claude:"
echo '    "Set up Cortex for my vault at ~/notes"'
echo ""
