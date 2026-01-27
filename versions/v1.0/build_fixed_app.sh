#!/bin/bash
# Fixed App Builder for Payroll Processor
# This script creates a working Mac application without py2app issues

echo "🔧 Building Fixed Payroll Processor App..."
echo "==========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

print_status "Working directory: $SCRIPT_DIR"

# Clean previous builds
print_status "Cleaning previous builds..."
rm -rf build dist

# Method 1: Try py2app with fixed settings
print_status "Attempting py2app build with fixed settings..."

# Set up virtual environment
source .venv/bin/activate

# Create a fixed setup.py
cat > setup_fixed.py << 'EOF'
#!/usr/bin/env python3
from setuptools import setup
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

APP = ['payroll_gui.py']
DATA_FILES = [
    ('', ['process_payroll.py', 'create_employee_reports.py']),
]

OPTIONS = {
    'argv_emulation': False,  # Disable to avoid Carbon issues
    'strip': False,  # Don't strip to avoid issues
    'optimize': 0,   # No optimization to avoid issues
    'plist': {
        'CFBundleName': 'Payroll Processor',
        'CFBundleDisplayName': 'Payroll Processor',
        'CFBundleGetInfoString': "Payroll Processing Application",
        'CFBundleIdentifier': 'com.payrollprocessor.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.12.0',
    },
    'packages': ['tkinter', 'tkinterdnd2', 'pandas', 'xlsxwriter'],
    'includes': [
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox',
        'tkinterdnd2', 'pandas', 'xlsxwriter', 'threading', 'tempfile',
        'subprocess', 're', 'os', 'datetime'
    ],
    'excludes': ['PyQt4', 'PyQt5', 'matplotlib', 'numpy', 'Carbon', '_carbon'],
    'iconfile': 'app_icon.icns' if os.path.exists('app_icon.icns') else None,
    'resources': [],
}

setup(
    name='Payroll Processor',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
EOF

# Try the fixed py2app build
if python setup_fixed.py py2app 2>/dev/null; then
    print_success "py2app build succeeded!"
    
    # Test the app
    if "dist/payroll_gui.app/Contents/MacOS/payroll_gui" 2>/dev/null; then
        print_success "App launches successfully!"
        
        # Rename to proper name
        if [ -d "dist/payroll_gui.app" ]; then
            mv "dist/payroll_gui.app" "dist/Payroll Processor.app"
        fi
        
        PY2APP_SUCCESS=true
    else
        print_warning "py2app built but app doesn't launch properly"
        PY2APP_SUCCESS=false
    fi
else
    print_warning "py2app build failed, using alternative method"
    PY2APP_SUCCESS=false
fi

# Method 2: Create simple app bundle (fallback)
if [ "$PY2APP_SUCCESS" != "true" ]; then
    print_status "Creating simple app bundle (fallback method)..."
    
    python3 create_simple_app.py
    
    if [ -d "dist/Payroll Processor.app" ]; then
        print_success "Simple app bundle created successfully!"
    else
        print_error "Failed to create app bundle!"
        exit 1
    fi
fi

# Verify the app works
print_status "Verifying app functionality..."

APP_PATH="dist/Payroll Processor.app"
if [ -d "$APP_PATH" ]; then
    print_success "App bundle exists: $APP_PATH"
    
    # Check if it can be launched
    if open "$APP_PATH" 2>/dev/null; then
        print_success "App launches without errors!"
    else
        print_warning "App may have launch issues"
    fi
else
    print_error "App bundle not found!"
    exit 1
fi

# Clean up temporary files
rm -f setup_fixed.py

# Create installer if app exists
if [ -d "$APP_PATH" ]; then
    print_status "Creating installer packages..."
    ./create_simple_installer.sh
    
    print_success "Build completed successfully!"
    echo ""
    echo "📦 Created packages:"
    echo "   • dist/Payroll Processor.app (Mac application)"
    echo "   • PayrollProcessor_Installer/ (installer folder)"
    if [ -f "PayrollProcessor_v1.0_macOS.zip" ]; then
        echo "   • PayrollProcessor_v1.0_macOS.zip (zip archive)"
    fi
    if [ -f "PayrollProcessor_v1.0_macOS.dmg" ]; then
        echo "   • PayrollProcessor_v1.0_macOS.dmg (disk image)"
    fi
    echo ""
    echo "🚀 To test: open 'dist/Payroll Processor.app'"
    echo "📦 To distribute: use the installer packages"
    
else
    print_error "Build failed - no app bundle created"
    exit 1
fi

print_success "Fixed app build completed!"