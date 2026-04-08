#!/usr/bin/env python3
"""
Cortex Init — One-command setup for everything.

Walks through the entire setup interactively:
1. Asks for vault path (or uses current directory)
2. Asks for Neon connection string (with link to sign up)
3. Creates .cortex/config.yaml
4. Adds config to .gitignore
5. Installs Python dependencies
6. Creates the Postgres table
7. Indexes all existing .md files
8. Verifies with a test query
9. Optionally sets up a VPS via SSH

Usage:
    python cortex_init.py
    python cortex_init.py --vault ~/notes
    python cortex_init.py --vault ~/notes --neon "postgresql://..."
    python cortex_init.py --vault ~/notes --neon "postgresql://..." --no-interactive
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Ensure we can import cortex_common from the same directory
sys.path.insert(0, str(Path(__file__).parent))


def print_header():
    print()
    print("  ╔═══════════════════════════════════╗")
    print("  ║         CORTEX  INIT              ║")
    print("  ║   Long-term memory for Claude     ║")
    print("  ╚═══════════════════════════════════╝")
    print()


def ask(prompt, default=None):
    """Ask user for input with optional default."""
    if default:
        result = input(f"  {prompt} [{default}]: ").strip()
        return result if result else default
    else:
        result = input(f"  {prompt}: ").strip()
        return result


def ask_yn(prompt, default="y"):
    """Ask yes/no question."""
    suffix = "[Y/n]" if default == "y" else "[y/N]"
    result = input(f"  {prompt} {suffix}: ").strip().lower()
    if not result:
        return default == "y"
    return result in ("y", "yes")


def check_dependencies():
    """Check and install Python dependencies."""
    print("\n📦 Checking dependencies...")
    missing = []
    for pkg, import_name in [("psycopg2-binary", "psycopg2"), ("pyyaml", "yaml")]:
        try:
            __import__(import_name)
            print(f"  ✓ {pkg}")
        except ImportError:
            missing.append(pkg)
            print(f"  ✗ {pkg} (not installed)")

    if missing:
        print(f"\n  Installing: {', '.join(missing)}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages"] + missing,
            capture_output=True
        )
        # Verify installation
        for pkg, import_name in [("psycopg2-binary", "psycopg2"), ("pyyaml", "yaml")]:
            try:
                __import__(import_name)
            except ImportError:
                print(f"\n  ✗ Failed to install {pkg}. Install manually:")
                print(f"    pip install {pkg}")
                sys.exit(1)
        print("  ✓ All dependencies installed")
    else:
        print("  ✓ All dependencies present")


def create_config(vault_path, neon_conn):
    """Create .cortex/config.yaml."""
    config_dir = vault_path / ".cortex"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.yaml"

    if config_path.exists():
        if not ask_yn("Config already exists. Overwrite?", "n"):
            print("  Using existing config.")
            return config_path

    config_content = f"""vault_path: {vault_path}
neon_connection_string: {neon_conn}

git:
  auto_commit: true
  auto_push: true
  commit_prefix: "cortex:"
  remote: origin
  branch: main

schema:
  extensions: []
"""
    config_path.write_text(config_content)
    print(f"  ✓ Created {config_path}")
    return config_path


def protect_gitignore(vault_path):
    """Ensure .cortex/config.yaml is in .gitignore."""
    gitignore = vault_path / ".gitignore"
    entry = ".cortex/config.yaml"

    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content:
            print("  ✓ .gitignore already protects config")
            return

    with open(gitignore, "a") as f:
        f.write(f"\n# Cortex config contains database credentials\n{entry}\n")
    print("  ✓ Added .cortex/config.yaml to .gitignore")


def test_neon_connection(neon_conn):
    """Test the Neon connection string."""
    print("\n🔌 Testing Neon connection...")
    try:
        import psycopg2
        conn_string = neon_conn
        if "sslmode" not in conn_string:
            conn_string += "?sslmode=require" if "?" not in conn_string else "&sslmode=require"
        conn = psycopg2.connect(conn_string)
        conn.close()
        print("  ✓ Connected to Neon successfully")
        return True
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        print("\n  Check your connection string and try again.")
        print("  It should look like: postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require")
        return False


def run_setup(config_path):
    """Run cortex_setup.py to create table and index files."""
    print("\n🗄️  Creating database table and indexing files...")
    script = Path(__file__).parent / "cortex_setup.py"
    result = subprocess.run(
        [sys.executable, str(script), "--config", str(config_path)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        # Print output but indent it
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
        return True
    else:
        print(f"  ✗ Setup failed:")
        for line in (result.stderr or result.stdout).strip().split("\n"):
            print(f"    {line}")
        return False


def run_verify(config_path):
    """Run a test query to verify everything works."""
    print("\n🔍 Verifying with a test query...")
    script = Path(__file__).parent / "cortex_query.py"
    result = subprocess.run(
        [sys.executable, str(script), "--config", str(config_path),
         "--status", "active", "--limit", "3"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        output = result.stdout.strip()
        if "No matching notes" in output:
            print("  ✓ Query works (no active notes yet — that's normal for a fresh vault)")
        else:
            for line in output.split("\n")[:6]:
                print(f"  {line}")
            print("  ✓ Query returned results successfully")
        return True
    else:
        print(f"  ✗ Query failed: {result.stderr or result.stdout}")
        return False


def setup_vps(vault_path, neon_conn, config_path):
    """Optionally set up the VPS via SSH."""
    print("\n🖥️  VPS Setup")
    print("  If you run Open Claw on a VPS, we can set it up there too.")

    if not ask_yn("Set up a VPS now?", "n"):
        print("  Skipped. You can set up the VPS later — see the setup guide.")
        return

    ssh_host = ask("SSH host (e.g., user@your-vps.com)")
    vps_vault = ask("Vault path on VPS", str(vault_path).replace(str(Path.home()), "~"))
    git_repo = ask("Git repo URL for the vault")

    print(f"\n  Setting up Cortex on {ssh_host}...")

    # Build the remote setup commands
    remote_commands = f"""
set -e
echo "Cloning vault repo..."
git clone {git_repo} {vps_vault} 2>/dev/null || (cd {vps_vault} && git pull)

echo "Creating config..."
mkdir -p {vps_vault}/.cortex
cat > {vps_vault}/.cortex/config.yaml << 'CONFIGEOF'
vault_path: {vps_vault}
neon_connection_string: {neon_conn}

git:
  auto_commit: true
  auto_push: true
  commit_prefix: "cortex:"
  remote: origin
  branch: main

schema:
  extensions: []
CONFIGEOF

echo "Installing dependencies..."
pip install psycopg2-binary pyyaml --break-system-packages 2>/dev/null || pip install psycopg2-binary pyyaml

echo "VPS setup complete."
"""

    result = subprocess.run(
        ["ssh", ssh_host, remote_commands],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
        print(f"  ✓ VPS configured at {ssh_host}:{vps_vault}")
        print(f"  Note: Run cortex_setup.py on the VPS to create/verify the table:")
        print(f"    ssh {ssh_host} 'python cortex_setup.py --config {vps_vault}/.cortex/config.yaml'")
    else:
        print(f"  ✗ VPS setup failed: {result.stderr}")
        print(f"  You can set it up manually — see references/setup-guide.md")


def main():
    parser = argparse.ArgumentParser(description="Cortex: one-command setup")
    parser.add_argument("--vault", help="Path to your vault (default: ask interactively)")
    parser.add_argument("--neon", help="Neon connection string (default: ask interactively)")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Don't ask questions, use defaults + provided args")
    args = parser.parse_args()

    print_header()

    # Step 1: Dependencies
    check_dependencies()

    # Step 2: Vault path
    if args.vault:
        vault_path = Path(args.vault).expanduser().resolve()
    elif args.no_interactive:
        vault_path = Path.cwd()
    else:
        print("\n📁 Where's your vault?")
        print("  This is the folder where your .md files live (or will live).")
        print("  If you use Obsidian, it's your vault folder.\n")
        raw = ask("Vault path", str(Path.cwd()))
        vault_path = Path(raw).expanduser().resolve()

    if not vault_path.exists():
        print(f"\n  Creating {vault_path}...")
        vault_path.mkdir(parents=True)
    print(f"  ✓ Vault: {vault_path}")

    # Step 3: Neon connection
    if args.neon:
        neon_conn = args.neon
    elif args.no_interactive:
        print("\n  ✗ --neon is required in non-interactive mode")
        sys.exit(1)
    else:
        print("\n🐘 Neon Postgres connection string")
        print("  Don't have one? Sign up free at https://neon.tech")
        print("  Create a project → copy the connection string.\n")
        neon_conn = ask("Connection string")

    # Test connection
    if not test_neon_connection(neon_conn):
        if not args.no_interactive and ask_yn("Continue anyway?", "n"):
            pass
        else:
            sys.exit(1)

    # Step 4: Create config
    print("\n⚙️  Creating config...")
    config_path = create_config(vault_path, neon_conn)

    # Step 5: Protect credentials
    protect_gitignore(vault_path)

    # Step 6: Setup (create table + index)
    if not run_setup(config_path):
        print("\n  Setup hit an error. Check the output above and try again.")
        sys.exit(1)

    # Step 7: Verify
    run_verify(config_path)

    # Step 8: VPS (optional)
    if not args.no_interactive:
        setup_vps(vault_path, neon_conn, config_path)

    # Done!
    print("\n" + "=" * 50)
    print("  ✓ Cortex is ready!")
    print("=" * 50)
    print()
    print("  Your vault: " + str(vault_path))
    print("  Config:     " + str(config_path))
    print()
    print("  Try these:")
    print('    "Save a note about [topic]"')
    print('    "Find my notes about [keyword]"')
    print('    "Sync my vault"')
    print()


if __name__ == "__main__":
    main()
