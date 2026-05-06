"""
AI-Enhanced Courier System - Setup Script
Automated setup for first-time users
"""

import subprocess
import sys
import os
from pathlib import Path

def print_header(text):
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")

def print_step(step_num, total, description):
    """Print step progress"""
    print(f"[{step_num}/{total}] {description}...")

def run_command(command, description, show_output=False):
    """Run a command and handle errors"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            text=True,
            capture_output=not show_output,
            encoding='utf-8',
            errors='replace'
        )
        if result.stdout and not show_output:
            print(result.stdout)
        print(f"✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Error: {description} failed")
        if e.stderr:
            print(f"Error details: {e.stderr}")
        return False

def check_ollama():
    """Check if Ollama is reachable (optional — app handles absence gracefully)."""
    import os
    import urllib.request
    import urllib.error

    url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    print(f"Checking Ollama at {url}...")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2) as r:
            import json
            tags = json.loads(r.read()).get("models", [])
            names = [t.get("name", "") for t in tags]
            if model in names:
                print(f"✓ Ollama reachable, model '{model}' available")
            else:
                print(f"⚠ Ollama reachable but model '{model}' missing")
                print(f"  Run: ollama pull {model}")
    except Exception:
        print(f"⚠ Ollama not reachable at {url} — AI features will be disabled")
        print(f"  Start it with: docker compose up -d ollama  (or `ollama serve` natively)")
    return True  # never block setup


def main():
    print_header("AI-Enhanced Courier System - Setup Wizard")

    # Check if virtual environment is activated
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("⚠ Warning: Virtual environment not activated!")
        print("\nRecommended: Activate virtual environment first:")
        print("  Windows: .venv\\Scripts\\activate")
        print("  Linux/Mac: source .venv/bin/activate")
        response = input("\nContinue without virtual environment? (y/n): ")
        if response.lower() != 'y':
            print("\nSetup cancelled. Please activate virtual environment and try again.")
            return

    # Step 1: Check Ollama (non-fatal — app degrades gracefully if absent)
    print_step(1, 4, "Checking prerequisites")
    check_ollama()
    print("\n✓ Prerequisites checked\n")

    # Step 2: Install Python dependencies
    print_step(2, 4, "Installing Python dependencies")
    print("\n⏱ This may take 1-2 minutes...")
    print("Please be patient...\n")

    if not run_command(
        f'"{sys.executable}" -m pip install --upgrade pip',
        "Upgrading pip"
    ):
        print("\nWarning: pip upgrade failed, continuing anyway...")

    if not run_command(
        f'"{sys.executable}" -m pip install -r requirements.txt',
        "Installing dependencies",
        show_output=False
    ):
        print("\n✗ Dependency installation failed!")
        print("Common issues:")
        print("  - Insufficient disk space")
        print("  - Network connectivity issues")
        return

    # Step 3: Initialize database
    print_step(3, 4, "Initializing database")
    if not run_command(
        f'"{sys.executable}" -m flask init-db',
        "Database initialization"
    ):
        print("\n✗ Database initialization failed!")
        return

    # Step 4: Seed database with demo data
    print_step(4, 4, "Seeding database with demo data")
    if not run_command(
        f'"{sys.executable}" -m flask seed-db',
        "Database seeding"
    ):
        print("\n✗ Database seeding failed!")
        return

    # Success!
    print_header("Setup Complete!")

    print("🎉 Your AI-Enhanced Courier System is ready!\n")
    print("=" * 70)
    print("DEMO LOGIN CREDENTIALS:")
    print("=" * 70)
    print("\n  ADMIN:")
    print("    • admin / admin123")
    print("\n  RESTAURANTS:")
    print("    • pizza_palace / rest123  (Pizza Palace Ostrava)")
    print("    • burger_king / rest123   (Burger Kingdom Stodolní)")
    print("\n  COURIERS:")
    print("    • john_courier / courier123  (John Doe)")
    print("    • jane_courier / courier123  (Jane Smith)")
    print("    • mike_courier / courier123  (Mike Johnson)")
    print("\n" + "=" * 70)

    print("\n📝 Important Notes:")
    print("  • AI models run inside Ollama (separate service at OLLAMA_URL)")
    print("  • Pull models once:  ollama pull qwen2.5:3b  &&  ollama pull moondream")
    print("  • Models are pre-warmed at app startup for instant first response")
    print("  • AI insights are cached for 24 hours to reduce model calls")
    print("  • Recommended: Docker Compose (docker compose up -d) — bundles Postgres + Ollama")

    print("\n🚀 Starting the application...\n")
    print("=" * 70)
    print("Access at: http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print("=" * 70 + "\n")

    # Start the application
    try:
        subprocess.run(f'"{sys.executable}" app.py', shell=True)
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped. Thanks for using the Courier System!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        print("Please report this issue if it persists.")
