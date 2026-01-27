#!/bin/bash
# Payroll Processor GUI Launcher (v1.1)
# Sets up a local virtualenv inside versions/v1.1 and launches the GUI.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$VERSION_DIR/src"
REQ_FILE="$VERSION_DIR/requirements.txt"
VENV_DIR="$VERSION_DIR/.venv"

echo "🔧 Setting up Payroll Processor v1.1..."

# Ensure PATH contains locations Homebrew uses when launching from Finder
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

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "📚 Installing dependencies..."
pip install -r "$REQ_FILE"

# Check if pdftotext is available
if ! command -v pdftotext &> /dev/null; then
    echo "⚠️  Warning: pdftotext not found!"
    echo "   Please install poppler-utils:"
    echo "   brew install poppler"
    echo ""
fi

# Launch the GUI
echo "🚀 Launching Payroll Processor GUI..."
cd "$SRC_DIR"
python payroll_gui.py

echo "✅ Done!"
