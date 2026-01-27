#!/bin/bash
# Payroll Processor - Mac App Builder and Installer
# This script builds a standalone Mac application

echo "🏗️  Building Payroll Processor Mac Application..."
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
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

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "This script is designed for macOS only."
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

print_status "Working directory: $SCRIPT_DIR"

# Check for required tools
print_status "Checking system requirements..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is required but not installed."
    exit 1
fi

# Check for pdftotext
if ! command -v pdftotext &> /dev/null; then
    print_warning "pdftotext not found. Installing via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install poppler
    else
        print_error "Homebrew not found. Please install poppler manually:"
        print_error "  brew install poppler"
        exit 1
    fi
fi

# Check for iconutil (should be available on macOS)
if ! command -v iconutil &> /dev/null; then
    print_error "iconutil not found. This tool is required on macOS."
    exit 1
fi

print_success "System requirements check passed."

# Clean previous builds
print_status "Cleaning previous builds..."
rm -rf build dist

# Set up virtual environment
print_status "Setting up Python environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
print_status "Installing Python dependencies..."
pip install --upgrade pip
pip install py2app Pillow
pip install -r requirements.txt

# Create app icon if it doesn't exist
if [ ! -f "app_icon.icns" ]; then
    print_status "Creating application icon..."
    python create_icon.py
fi

# Build the application
print_status "Building Mac application..."
python setup.py py2app

if [ $? -eq 0 ]; then
    print_success "Application built successfully!"
    
    # Create installer directory
    print_status "Creating installer package..."
    
    INSTALLER_DIR="PayrollProcessor_Installer"
    rm -rf "$INSTALLER_DIR"
    mkdir "$INSTALLER_DIR"
    
    # Copy the app bundle
    cp -R "dist/payroll_gui.app" "$INSTALLER_DIR/Payroll Processor.app"
    
    # Create installer script
    cat > "$INSTALLER_DIR/install.sh" << 'EOF'
#!/bin/bash
# Payroll Processor Installer

echo "Installing Payroll Processor..."

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This application is designed for macOS only."
    exit 1
fi

# Get the directory where this script is located
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Payroll Processor.app"
DEST_DIR="/Applications"

# Check if app exists in installer
if [ ! -d "$INSTALLER_DIR/$APP_NAME" ]; then
    echo "Error: Application not found in installer."
    exit 1
fi

# Copy to Applications folder
echo "Installing to /Applications..."
if cp -R "$INSTALLER_DIR/$APP_NAME" "$DEST_DIR/"; then
    echo "✅ Payroll Processor installed successfully!"
    echo ""
    echo "You can now find 'Payroll Processor' in your Applications folder."
    echo "You may also want to add it to your Dock for easy access."
    echo ""
    echo "Note: Make sure you have 'pdftotext' installed:"
    echo "  brew install poppler"
else
    echo "❌ Installation failed. You may need administrator privileges."
    echo "Try running with sudo or manually copy the app to /Applications"
fi
EOF
    
    chmod +x "$INSTALLER_DIR/install.sh"
    
    # Create README
    cat > "$INSTALLER_DIR/README.txt" << 'EOF'
Payroll Processor - Mac Application
===================================

This package contains the Payroll Processor application for macOS.

INSTALLATION:
1. Double-click "install.sh" or run it from Terminal
2. The app will be installed to your Applications folder

REQUIREMENTS:
- macOS 10.12 or later
- pdftotext utility (install with: brew install poppler)

USAGE:
1. Launch "Payroll Processor" from Applications
2. Drag and drop ZIP files containing payroll PDFs
3. Click "Generate Reports" to create Excel reports

The application processes Greek payroll documents and generates
employee reports in Excel format.

For support, please contact your system administrator.
EOF
    
    # Create DMG installer (if hdiutil is available)
    print_status "Creating DMG installer..."
    DMG_NAME="PayrollProcessor_v1.0.dmg"
    
    if command -v hdiutil &> /dev/null; then
        # Create temporary DMG
        hdiutil create -size 200m -fs HFS+ -volname "Payroll Processor" temp.dmg
        
        # Mount DMG
        hdiutil attach temp.dmg -mountpoint /tmp/payroll_dmg
        
        # Copy installer contents
        cp -R "$INSTALLER_DIR"/* /tmp/payroll_dmg/
        
        # Create Applications symlink for easy drag-and-drop
        ln -s /Applications /tmp/payroll_dmg/Applications
        
        # Unmount and convert to read-only
        hdiutil detach /tmp/payroll_dmg
        hdiutil convert temp.dmg -format UDZO -o "$DMG_NAME"
        rm temp.dmg
        
        print_success "DMG installer created: $DMG_NAME"
    else
        print_warning "hdiutil not available. Skipping DMG creation."
    fi
    
    # Create ZIP package as alternative
    print_status "Creating ZIP package..."
    zip -r "PayrollProcessor_v1.0.zip" "$INSTALLER_DIR"
    
    print_success "Installation packages created!"
    echo ""
    echo "📦 Available packages:"
    echo "   • $INSTALLER_DIR/ (installer folder)"
    if [ -f "$DMG_NAME" ]; then
        echo "   • $DMG_NAME (disk image)"
    fi
    echo "   • PayrollProcessor_v1.0.zip (zip archive)"
    echo ""
    echo "🚀 To test the app:"
    echo "   1. Run: cd '$INSTALLER_DIR' && ./install.sh"
    echo "   2. Launch from Applications folder"
    
else
    print_error "Application build failed!"
    echo "Check the output above for errors."
    exit 1
fi

print_success "Build process completed!"