#!/bin/bash
# Simple Mac App Installer for Payroll Processor
# This creates a simple installer package without the complex build process

echo "📦 Creating Simple Payroll Processor Installer..."
echo "================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

APP_VERSION="${APP_VERSION:-1.2.0}"
APP_VERSION_SHORT="${APP_VERSION%.*}"
if [ "$APP_VERSION_SHORT" = "$APP_VERSION" ]; then
    APP_VERSION_SHORT="$APP_VERSION"
fi

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

# Get important directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$VERSION_DIR/../.." && pwd)"

cd "$REPO_ROOT"

RELEASE_ROOT="$REPO_ROOT/releases/v${APP_VERSION_SHORT}"
INSTALLER_DIR="$RELEASE_ROOT/PayrollProcessor_Installer"
ZIP_BASENAME="PayrollProcessor_v${APP_VERSION_SHORT}_macOS.zip"
DMG_BASENAME="PayrollProcessor_v${APP_VERSION_SHORT}_macOS.dmg"

# Check if app exists
if [ ! -d "$REPO_ROOT/dist/Payroll Processor.app" ]; then
    print_error "App bundle not found. Please run create_simple_app.py first."
    exit 1
fi

print_status "Preparing release directory: $RELEASE_ROOT"
mkdir -p "$RELEASE_ROOT"

print_status "Creating installer package..."

# Create installer directory
rm -rf "$INSTALLER_DIR"
mkdir "$INSTALLER_DIR"

# Copy the app bundle
print_status "Copying application bundle..."
cp -R "$REPO_ROOT/dist/Payroll Processor.app" "$INSTALLER_DIR/Payroll Processor.app"

# Create simple installer script
print_status "Creating installer script..."
cat > "$INSTALLER_DIR/Install Payroll Processor.command" << 'EOF'
#!/bin/bash
# Payroll Processor Simple Installer

echo "🔧 Installing Payroll Processor..."

# Get the directory where this script is located
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Payroll Processor.app"
DEST_DIR="/Applications"

# Check if app exists in installer
if [ ! -d "$INSTALLER_DIR/$APP_NAME" ]; then
    echo "❌ Error: Application not found in installer."
    read -p "Press Enter to exit..."
    exit 1
fi

# Check if Applications directory exists and is writable
if [ ! -w "$DEST_DIR" ]; then
    echo "⚠️  Need administrator privileges to install to Applications folder."
    echo "You will be prompted for your password."
    sudo cp -R "$INSTALLER_DIR/$APP_NAME" "$DEST_DIR/"
    RESULT=$?
else
    cp -R "$INSTALLER_DIR/$APP_NAME" "$DEST_DIR/"
    RESULT=$?
fi

if [ $RESULT -eq 0 ]; then
    echo "✅ Payroll Processor installed successfully!"
    echo ""
    echo "📍 The application has been installed to:"
    echo "   /Applications/Payroll Processor.app"
    echo ""
    echo "🚀 You can now:"
    echo "   1. Find it in Launchpad"
    echo "   2. Add it to your Dock"
    echo "   3. Launch it from Finder"
    echo ""
    echo "⚠️  Important: Make sure pdftotext is installed:"
    echo "   brew install poppler"
    echo ""
    echo "✨ Ready to process payroll files!"
else
    echo "❌ Installation failed."
    echo "   Try dragging the app manually to /Applications"
fi

echo ""
read -p "Press Enter to close this window..."
EOF

chmod +x "$INSTALLER_DIR/Install Payroll Processor.command"

# Create uninstaller
print_status "Creating uninstaller..."
cat > "$INSTALLER_DIR/Uninstall Payroll Processor.command" << 'EOF'
#!/bin/bash
# Payroll Processor Uninstaller

echo "🗑️  Uninstalling Payroll Processor..."

APP_PATH="/Applications/Payroll Processor.app"

if [ -d "$APP_PATH" ]; then
    read -p "Are you sure you want to remove Payroll Processor? (y/N): " confirm
    if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        if rm -rf "$APP_PATH"; then
            echo "✅ Payroll Processor has been removed."
        else
            echo "❌ Failed to remove application. You may need administrator privileges."
            echo "Try: sudo rm -rf '$APP_PATH'"
        fi
    else
        echo "❌ Uninstallation cancelled."
    fi
else
    echo "ℹ️  Payroll Processor is not installed in /Applications"
fi

echo ""
read -p "Press Enter to close this window..."
EOF

chmod +x "$INSTALLER_DIR/Uninstall Payroll Processor.command"

# Create README
print_status "Creating documentation..."
cat > "$INSTALLER_DIR/README.txt" << 'EOF'
Payroll Processor for macOS
============================

INSTALLATION:
1. Double-click "Install Payroll Processor.command"
2. Follow the prompts
3. The app will be installed to /Applications

REQUIREMENTS:
- macOS 10.12 or later
- pdftotext utility (install with: brew install poppler)

USAGE:
1. Launch "Payroll Processor" from Applications
2. Drag and drop ZIP files containing Greek payroll PDFs
3. Click "Generate Reports" to create Excel files
4. Choose where to save the employee reports

FEATURES:
- Drag-and-drop interface
- Processes multiple ZIP files at once
- Extracts employee data from Greek payroll PDFs
- Generates Excel reports per employee
- Progress tracking and status updates

SUPPORTED DOCUMENT TYPES:
- Regular payslips (ΑΠΟΔΕΙΞΕΙΣ ΠΛΗΡΩΜΩΝ)
- Vacation allowances (ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ)
- Christmas/Easter bonuses (ΔΩΡΟ)
- Unused leave compensation (ΑΠΟΖΗΜΙΩΣΗ)

TROUBLESHOOTING:
- If drag-and-drop doesn't work, use the "Browse" button
- Make sure pdftotext is installed: brew install poppler
- For permission issues, try running the installer with administrator privileges

UNINSTALLATION:
- Double-click "Uninstall Payroll Processor.command"
- Or manually delete from /Applications

For support, contact your system administrator.
EOF

# Create version info
cat > "$INSTALLER_DIR/VERSION.txt" << EOF
Payroll Processor v${APP_VERSION}
Built: $(date '+%Y-%m-%d %H:%M:%S')
Platform: macOS Universal (Intel/Apple Silicon)
Python: $(python3 --version)
EOF

# Create ZIP package
print_status "Creating ZIP archive..."
(
    cd "$RELEASE_ROOT" && zip -r "$ZIP_BASENAME" "PayrollProcessor_Installer" > /dev/null
)

# Create DMG if possible
if command -v hdiutil &> /dev/null; then
    print_status "Creating DMG installer..."
    
    # Create temporary DMG
    hdiutil create -size 100m -fs HFS+ -volname "Payroll Processor Installer" "$RELEASE_ROOT/temp.dmg" > /dev/null 2>&1
    
    # Mount DMG
    hdiutil attach "$RELEASE_ROOT/temp.dmg" -mountpoint /tmp/payroll_dmg > /dev/null 2>&1
    
    # Copy installer contents
    cp -R "$INSTALLER_DIR"/* /tmp/payroll_dmg/ 2>/dev/null
    
    # Create Applications symlink
    ln -s /Applications /tmp/payroll_dmg/Applications 2>/dev/null
    
    # Unmount and convert to read-only
    hdiutil detach /tmp/payroll_dmg > /dev/null 2>&1
    hdiutil convert "$RELEASE_ROOT/temp.dmg" -format UDZO -o "$RELEASE_ROOT/$DMG_BASENAME" > /dev/null 2>&1
    rm -f "$RELEASE_ROOT/temp.dmg"
    
    if [ -f "$RELEASE_ROOT/$DMG_BASENAME" ]; then
        print_success "DMG installer created: releases/v${APP_VERSION_SHORT}/$DMG_BASENAME"
    fi
fi

print_success "Installer package created successfully!"
echo ""
echo "📦 Available packages:"
echo "   • releases/v${APP_VERSION_SHORT}/PayrollProcessor_Installer/"
echo "   • releases/v${APP_VERSION_SHORT}/$ZIP_BASENAME"
if [ -f "$RELEASE_ROOT/$DMG_BASENAME" ]; then
    echo "   • releases/v${APP_VERSION_SHORT}/$DMG_BASENAME"
fi
echo ""
echo "🚀 To install:"
echo "   1. Open the installer folder"
echo "   2. Double-click 'Install Payroll Processor.command'"
echo "   3. Follow the prompts"
echo ""
echo "📋 To test the app:"
echo "   1. Install as above"
echo "   2. Launch from Applications or Launchpad"
echo "   3. Drag some payroll ZIP files to test"

print_success "Installation package ready!"
