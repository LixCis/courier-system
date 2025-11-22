"""
Quick setup script for the Courier System MVP
Run this script to set up and start the application
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"\n{'='*60}")
    print(f"{description}...")
    print(f"{'='*60}")
    try:
        result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        if e.stderr:
            print(e.stderr)
        return False

def main():
    print("\n" + "="*60)
    print("Courier System MVP - Quick Setup")
    print("="*60)

    # Check if virtual environment is activated
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("\nWarning: Virtual environment not activated!")
        print("Please activate your virtual environment first:")
        print("  Windows: .venv\\Scripts\\activate")
        print("  Linux/Mac: source .venv/bin/activate")
        response = input("\nContinue anyway? (y/n): ")
        if response.lower() != 'y':
            return

    # Install dependencies
    if not run_command(f"{sys.executable} -m pip install -r requirements.txt", "Installing dependencies"):
        print("\nFailed to install dependencies!")
        return

    # Initialize database
    if not run_command(f"{sys.executable} -m flask init-db", "Initializing database"):
        print("\nFailed to initialize database!")
        return

    # Seed database
    if not run_command(f"{sys.executable} -m flask seed-db", "Seeding database with demo data"):
        print("\nFailed to seed database!")
        return

    print("\n" + "="*60)
    print("Setup Complete!")
    print("="*60)
    print("\nDemo Login Credentials:")
    print("-" * 60)
    print("Admin:      admin / admin123")
    print("Restaurant: pizza_palace / rest123")
    print("Courier:    john_courier / courier123")
    print("-" * 60)
    print("\nStarting the application...")
    print("Access at: http://localhost:5000")
    print("\nPress Ctrl+C to stop the server\n")

    # Run the application
    subprocess.run(f"{sys.executable} app.py", shell=True)

if __name__ == "__main__":
    main()
