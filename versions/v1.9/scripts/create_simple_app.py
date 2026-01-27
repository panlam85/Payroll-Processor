#!/usr/bin/env python3
"""
Simple setup script for creating a Mac app bundle without py2app issues.
This creates a basic app structure that works reliably.
"""

import os
import shutil
import stat
import plistlib
import subprocess
from pathlib import Path
from typing import Optional

APP_VERSION = "1.9.0"
APP_VERSION_SHORT = APP_VERSION.rsplit(".", 1)[0] if "." in APP_VERSION else APP_VERSION

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
VERSION_DIR = SCRIPT_DIR.parent
REPO_ROOT = VERSION_DIR.parent.parent
SRC_DIR = VERSION_DIR / "src"
RESOURCES_DIR = VERSION_DIR / "resources"
REQ_FILE = VERSION_DIR / "requirements.txt"
DIST_DIR = REPO_ROOT / "dist"
VENV_EMBED_DIR = VERSION_DIR / ".venv-embed"


def ensure_venv() -> Path:
    """Create or refresh a local venv for embedding."""
    if not VENV_EMBED_DIR.exists():
        print("🐍 Creating embedded Python venv...")
        subprocess.check_call(["python3", "-m", "venv", "--copies", str(VENV_EMBED_DIR)])
    print("📦 Installing Python dependencies into embedded venv...")
    pip_path = VENV_EMBED_DIR / "bin" / "pip"
    subprocess.check_call([str(pip_path), "install", "-r", str(REQ_FILE)])
    return VENV_EMBED_DIR


def find_poppler_prefix() -> Optional[Path]:
    """Return Homebrew poppler prefix if available."""
    try:
        output = subprocess.check_output(["brew", "--prefix", "poppler"], text=True).strip()
        prefix = Path(output)
        if prefix.exists():
            return prefix
    except Exception:
        return None
    return None

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

    # Embed Python venv
    venv_path = ensure_venv()
    embedded_venv = resources_dir / "venv"
    if embedded_venv.exists():
        shutil.rmtree(embedded_venv)
    shutil.copytree(venv_path, embedded_venv, symlinks=False)

    # Embed poppler (pdftotext) if available
    poppler_prefix = find_poppler_prefix()
    if poppler_prefix:
        pdftotext_src = poppler_prefix / "bin" / "pdftotext"
        lib_src = poppler_prefix / "lib"
        bin_dest = resources_dir / "bin"
        lib_dest = resources_dir / "lib" / "poppler"
        bin_dest.mkdir(parents=True, exist_ok=True)
        lib_dest.mkdir(parents=True, exist_ok=True)
        if pdftotext_src.exists():
            shutil.copy(pdftotext_src, bin_dest / "pdftotext")
            os.chmod(bin_dest / "pdftotext", 0o755)
        if lib_src.exists():
            for item in lib_src.glob("*"):
                dest = lib_dest / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy(item, dest)
    else:
        print("⚠️  Poppler not found via Homebrew; pdftotext will not be embedded.")
    
    # Create launcher script
    launcher_script = f"""#!/bin/bash
# Payroll Processor Launcher

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
RESOURCES_DIR="$SCRIPT_DIR/../Resources"

# Change to resources directory
cd "$RESOURCES_DIR"

EMBED_VENV="$RESOURCES_DIR/venv"
EMBED_BIN="$RESOURCES_DIR/bin"
EMBED_LIB="$RESOURCES_DIR/lib/poppler"

if [ -d "$EMBED_VENV" ]; then
    PYTHON_BIN="$EMBED_VENV/bin/python"
else
    osascript -e 'display dialog "Embedded Python not found. Please rebuild the app." buttons {{"OK"}} default button "OK"'
    exit 1
fi

if [ -x "$EMBED_BIN/pdftotext" ]; then
    PATH="$EMBED_BIN:$PATH"
    if [ -d "$EMBED_LIB" ]; then
        export DYLD_LIBRARY_PATH="$EMBED_LIB:$DYLD_LIBRARY_PATH"
    fi
fi

# Launch the GUI
"$PYTHON_BIN" payroll_gui.py
"""
    
    launcher_path = app_path / "Contents" / "MacOS" / "payroll_processor"
    with open(launcher_path, "w") as f:
        f.write(launcher_script)
    
    # Make launcher executable
    st = os.stat(launcher_path)
    os.chmod(launcher_path, st.st_mode | stat.S_IEXEC)
    
    # Ad-hoc sign to improve Finder launch behavior (no paid ID required)
    try:
        subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", str(app_path)])
        print("✅ Ad-hoc signed app bundle.")
    except Exception as exc:
        print(f"⚠️  Ad-hoc signing failed: {exc}")

    print(f"✅ Simple app bundle created: {app_path}")
    print("📝 Note: This app embeds Python and pdftotext when available on the build machine.")
    
    return app_path

if __name__ == "__main__":
    create_simple_app()
