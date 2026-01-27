#!/usr/bin/env python3
"""
Simple setup script for creating a Mac app bundle without py2app issues.
This creates a basic app structure that works reliably.
"""

import os
import shutil
import stat
import plistlib
from pathlib import Path

APP_VERSION = "1.3.0"
APP_VERSION_SHORT = APP_VERSION.rsplit(".", 1)[0] if "." in APP_VERSION else APP_VERSION

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
VERSION_DIR = SCRIPT_DIR.parent
REPO_ROOT = VERSION_DIR.parent.parent
SRC_DIR = VERSION_DIR / "src"
RESOURCES_DIR = VERSION_DIR / "resources"
REQ_FILE = VERSION_DIR / "requirements.txt"
DIST_DIR = REPO_ROOT / "dist"

def create_simple_app():
    """Create a simple app bundle without py2app."""
    
    print("🔧 Creating simple app bundle...")
    
    # Clean old builds
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    
    app_name = "Payroll Processor.app"
    app_path = DIST_DIR / app_name
    
    # Create app bundle structure
    (app_path / "Contents" / "MacOS").mkdir(parents=True)
    (app_path / "Contents" / "Resources").mkdir(parents=True)
    
    # Create Info.plist
    plist_data = {
        'CFBundleName': 'Payroll Processor',
        'CFBundleDisplayName': 'Payroll Processor',
        'CFBundleIdentifier': 'com.payrollprocessor.app',
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION_SHORT,
        'CFBundleExecutable': 'payroll_processor',
        'CFBundleIconFile': 'app_icon.icns',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.12.0',
        'NSHumanReadableCopyright': 'Copyright © 2025 Payroll Processor',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeExtensions': ['zip'],
                'CFBundleTypeName': 'ZIP Archive',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['public.zip-archive'],
            }
        ]
    }
    
    with open(app_path / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist_data, f)
    
    # Copy icon if it exists
    icon_path = RESOURCES_DIR / "app_icon.icns"
    resources_dir = app_path / "Contents" / "Resources"
    if icon_path.exists():
        shutil.copy(icon_path, resources_dir)
    
    # Copy Python files
    shutil.copy(SRC_DIR / "payroll_gui.py", resources_dir)
    shutil.copy(SRC_DIR / "process_payroll.py", resources_dir)
    shutil.copy(SRC_DIR / "create_employee_reports.py", resources_dir)
    shutil.copy(REQ_FILE, resources_dir)
    
    # Create launcher script
    launcher_script = f"""#!/bin/bash
# Payroll Processor Launcher

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
RESOURCES_DIR="$SCRIPT_DIR/../Resources"

# Ensure PATH mirrors a login shell so Finder launches pick up Homebrew tools
ensure_cli_paths() {{
    if [ -x /usr/libexec/path_helper ]; then
        # shellcheck disable=SC2046
        eval "$(/usr/libexec/path_helper -s)"
    fi

    local brew_dirs=(
        "/opt/homebrew/bin"
        "/usr/local/bin"
        "/opt/homebrew/opt/poppler/bin"
        "/usr/local/opt/poppler/bin"
    )

    for dir in "${{brew_dirs[@]}}"; do
        if [ -d "$dir" ] && [[ ":$PATH:" != *":$dir:"* ]]; then
            PATH="$dir:$PATH"
        fi
    done

    if command -v brew &> /dev/null; then
        local brew_prefix
        brew_prefix="$(brew --prefix poppler 2>/dev/null || brew --prefix 2>/dev/null)"
        if [ -n "$brew_prefix" ] && [ -d "$brew_prefix/bin" ] && [[ ":$PATH:" != *":$brew_prefix/bin:"* ]]; then
            PATH="$brew_prefix/bin:$PATH"
        fi
    fi

    export PATH
}}

ensure_cli_paths

# Change to resources directory
cd "$RESOURCES_DIR"

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    osascript -e 'display dialog "Python 3 is required but not installed. Please install Python 3 from python.org" buttons {{"OK"}} default button "OK"'
    exit 1
fi

# Check for pdftotext
if ! command -v pdftotext &> /dev/null; then
    osascript -e 'display dialog "pdftotext utility is required. Please install with: brew install poppler" buttons {{"OK"}} default button "OK"'
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Launch the GUI
python payroll_gui.py
"""
    
    launcher_path = app_path / "Contents" / "MacOS" / "payroll_processor"
    with open(launcher_path, "w") as f:
        f.write(launcher_script)
    
    # Make launcher executable
    st = os.stat(launcher_path)
    os.chmod(launcher_path, st.st_mode | stat.S_IEXEC)
    
    print(f"✅ Simple app bundle created: {app_path}")
    print("📝 Note: This app requires Python 3 and pdftotext to be installed on the target system")
    
    return app_path

if __name__ == "__main__":
    create_simple_app()
