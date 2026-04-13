#!/bin/bash
# Cortex Installer — Claude Code plugin
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/wynexlabs/cortex/main/install.sh | bash

set -e

VERSION=$(curl -s "https://api.github.com/repos/WynexLabs/cortex/releases/latest" | grep '"tag_name"' | sed 's/.*"tag_name": *"v\?\([^"]*\)".*/\1/')
VERSION=${VERSION:-"1.4.0"}
REPO="https://github.com/WynexLabs/cortex.git"
PLUGIN_DIR="${HOME}/.claude/plugins/cache/wynexlabs/cortex/${VERSION}"
SETTINGS="${HOME}/.claude/settings.json"

echo ""
echo "  ╔═══════════════════════════════════╗"
echo "  ║      Installing Cortex ${VERSION}       ║"
echo "  ║   Long-term memory for Claude     ║"
echo "  ╚═══════════════════════════════════╝"
echo ""

# Check dependencies
if ! command -v git &> /dev/null; then
    echo "  ✗ git is required. Install it first."
    exit 1
fi
if ! command -v python3 &> /dev/null; then
    echo "  ✗ python3 is required. Install it first."
    exit 1
fi

# Install plugin files
if [ -d "$PLUGIN_DIR" ]; then
    echo "  Updating existing installation..."
    git -C "$PLUGIN_DIR" pull --quiet
    echo "  ✓ Updated to ${VERSION}"
else
    echo "  Installing to ${PLUGIN_DIR}..."
    mkdir -p "$(dirname "$PLUGIN_DIR")"
    git clone --quiet "$REPO" "$PLUGIN_DIR"
    echo "  ✓ Installed"
fi

# Register plugin in ~/.claude/settings.json
if command -v python3 &> /dev/null && [ -f "$SETTINGS" ]; then
    python3 - <<PYEOF
import json, sys

settings_path = "${SETTINGS}"
with open(settings_path, "r") as f:
    settings = json.load(f)

# Add wynexlabs marketplace
marketplaces = settings.setdefault("extraKnownMarketplaces", {})
marketplaces.setdefault("wynexlabs", {
    "source": {"source": "github", "repo": "WynexLabs/cortex"}
})

# Enable the plugin
plugins = settings.setdefault("enabledPlugins", {})
plugins["cortex@wynexlabs"] = True

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print("  ✓ Registered in ~/.claude/settings.json")
PYEOF
elif [ ! -f "$SETTINGS" ]; then
    echo "  ⚠ No ~/.claude/settings.json found — add this manually:"
    echo '    "extraKnownMarketplaces": {"wynexlabs": {"source": {"source": "github", "repo": "WynexLabs/cortex"}}}'
    echo '    "enabledPlugins": {"cortex@wynexlabs": true}'
fi

# Install Python dependencies
echo "  Installing Python dependencies..."
pip install psycopg2-binary pyyaml --break-system-packages --quiet 2>/dev/null || \
pip install psycopg2-binary pyyaml --quiet 2>/dev/null || \
echo "  ⚠ Could not auto-install. Run: pip install psycopg2-binary pyyaml"

echo ""
echo "  ✓ Cortex installed!"
echo ""
echo "  Next — run init:"
echo "    python3 ${PLUGIN_DIR}/scripts/cortex_init.py"
echo ""
echo "  Or restart Claude Code and tell it:"
echo '    "Set up Cortex for my vault"'
echo ""
