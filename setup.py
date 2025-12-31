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

def check_build_tools():
    """Check if Visual C++ Build Tools are installed (Windows only)"""
    if sys.platform != "win32":
        return True

    print("Checking for Visual C++ Build Tools...")

    # Check for common MSVC installations
    program_files = [
        os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'),
        os.environ.get('ProgramFiles', 'C:\\Program Files')
    ]

    msvc_paths = [
        "Microsoft Visual Studio\\2026\\BuildTools\\VC\\Tools\\MSVC",
        "Microsoft Visual Studio\\2026\\Community\\VC\\Tools\\MSVC",
        "Microsoft Visual Studio\\2022\\BuildTools\\VC\\Tools\\MSVC",
        "Microsoft Visual Studio\\2022\\Community\\VC\\Tools\\MSVC",
        "Microsoft Visual Studio\\2019\\BuildTools\\VC\\Tools\\MSVC",
    ]

    for pf in program_files:
        for msvc in msvc_paths:
            full_path = os.path.join(pf, msvc)
            if os.path.exists(full_path):
                print(f"✓ Found Visual C++ Build Tools at: {full_path}")
                return True

    print("\n" + "!"*70)
    print("WARNING: Visual C++ Build Tools not detected!")
    print("!"*70)
    print("\nllama-cpp-python requires C++ compilation tools.")
    print("\nTo install Build Tools:")
    print("1. Download: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022")
    print("2. Run installer and select 'Desktop development with C++'")
    print("3. Restart computer after installation")
    print("4. Run this setup script again")
    print("\n" + "!"*70 + "\n")

    response = input("Continue anyway? Installation may fail. (y/n): ")
    return response.lower() == 'y'

def check_llama_model():
    """Check if Llama model exists"""
    model_path = Path("models/llama-3.2-3b.gguf")

    print("Checking for Llama 3.2-3B model...")

    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        print(f"✓ Found Llama model: {model_path} ({size_mb:.1f} MB)")
        return True
    else:
        print("\n" + "!"*70)
        print("ERROR: Llama model not found!")
        print("!"*70)
        print(f"\nExpected location: {model_path.absolute()}")
        print("\nDownload the model:")
        print("  URL: https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q6_K.gguf")
        print("  Size: ~2.5GB")
        print("\nAfter download:")
        print(f"  1. Rename to: llama-3.2-3b.gguf")
        print(f"  2. Place in: {model_path.parent.absolute()}")
        print("\n" + "!"*70 + "\n")
        return False

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

    # Step 1: Check Build Tools (Windows only)
    print_step(1, 5, "Checking prerequisites")
    if not check_build_tools():
        print("\nSetup cancelled. Please install Build Tools first.")
        return

    # Step 2: Check Llama model
    if not check_llama_model():
        print("\nSetup cancelled. Please add Llama model first.")
        return

    print("\n✓ All prerequisites met!\n")

    # Step 3: Install Python dependencies
    print_step(2, 5, "Installing Python dependencies")
    print("\n⏱ This may take 5-10 minutes (llama-cpp-python needs to compile)...")
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
        print("  - Build Tools not installed correctly")
        print("  - Insufficient disk space")
        print("  - Network connectivity issues")
        return

    # Step 4: Initialize database
    print_step(3, 5, "Initializing database")
    if not run_command(
        f'"{sys.executable}" -m flask init-db',
        "Database initialization"
    ):
        print("\n✗ Database initialization failed!")
        return

    # Step 5: Seed database with demo data
    print_step(4, 5, "Seeding database with demo data")
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
    print("  • Llama model (2.5GB) will load on first use (~5-10 seconds)")
    print("  • BLIP vision model (~990MB) downloads automatically on first photo analysis")
    print("  • AI insights are cached for 24 hours to reduce model calls")
    print("  • Total disk space needed: ~3.5GB (models + dependencies)")
    print("  • Recommended: 4GB+ RAM for optimal performance")

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
