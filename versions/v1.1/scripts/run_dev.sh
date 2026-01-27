#!/bin/bash
# Quick launcher for development testing (v1.1)
echo "🚀 Launching Payroll Processor v1.1 (Development Mode)..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$VERSION_DIR/src"
REQ_FILE="$VERSION_DIR/requirements.txt"
VENV_DIR="$VERSION_DIR/.venv"

# Ensure the PATH includes common locations for Homebrew utilities when
# launched from Finder or other environments that do not load shell profiles.
ensure_cli_paths() {
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

    for dir in "${brew_dirs[@]}"; do
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
}

ensure_cli_paths

# Check for virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Setting up virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install dependencies if needed
if ! python -c "import tkinterdnd2, pandas, xlsxwriter" 2>/dev/null; then
    echo "📚 Installing dependencies..."
    pip install -r "$REQ_FILE"
fi

# Check for pdftotext
if ! command -v pdftotext &> /dev/null; then
    echo "⚠️  Warning: pdftotext not found!"
    echo "   Install with: brew install poppler"
fi

# Launch the GUI
echo "🎯 Starting Payroll Processor..."
cd "$SRC_DIR"
python payroll_gui.py
