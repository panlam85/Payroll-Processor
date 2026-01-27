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

APP_VERSION="${APP_VERSION:-2.2.0}"
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
AGREEMENT_SOURCE="$REPO_ROOT/user_agreement.md"
AGREEMENT_TXT="$INSTALLER_DIR/User Agreement.txt"

# Check if app exists
if [ ! -d "$REPO_ROOT/dist/Payroll Processor.app" ]; then
    print_error "App bundle not found. Please run create_simple_app.py first."
    exit 1
fi

# Verify required files exist in bundle
if [ ! -f "$REPO_ROOT/dist/Payroll Processor.app/Contents/Resources/process_payroll.py" ]; then
    print_error "App bundle missing process_payroll.py. Rebuild the app bundle."
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
USER_APPS="$HOME/Applications"
DEST_DIR="$USER_APPS"

mkdir -p "$USER_APPS"

# Check if app exists in installer
if [ ! -d "$INSTALLER_DIR/$APP_NAME" ]; then
    echo "❌ Error: Application not found in installer."
    read -p "Press Enter to exit..."
    exit 1
fi

rm -rf "$DEST_DIR/$APP_NAME"
cp -R "$INSTALLER_DIR/$APP_NAME" "$DEST_DIR/"
RESULT=$?

# Remove quarantine attribute if present
if [ $RESULT -eq 0 ]; then
    xattr -dr com.apple.quarantine "$DEST_DIR/$APP_NAME" 2>/dev/null
    if command -v codesign &> /dev/null; then
        codesign --force --deep --sign - "$DEST_DIR/$APP_NAME" >/dev/null 2>&1 || true
    fi
fi

if [ $RESULT -eq 0 ]; then
    echo "✅ Payroll Processor installed successfully!"
    echo ""
    echo "📍 The application has been installed to:"
    echo "   $USER_APPS/Payroll Processor.app"
    echo ""
    echo "🚀 You can now:"
    echo "   1. Open it from your Home Applications folder"
    echo "   2. Drag it into the Dock if you want"
    echo "   3. Move it to /Applications later if needed"
    echo ""
    echo "⚠️  Important: Make sure pdftotext is installed:"
    echo "   brew install poppler"
    echo ""
    echo "✨ Ready to process payroll files!"
else
    echo "❌ Installation failed."
    echo "   Try running this installer again"
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
- No external dependencies (Python and pdftotext are bundled)

USAGE:
1. Launch "Payroll Processor" from your Home Applications folder
2. Drag and drop ZIP files containing Greek payroll PDFs
3. Click "Generate Reports" to create Excel files
4. Pick an output folder and receive two workbooks (summary + detail)

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
- For permission issues, try running the installer with administrator privileges

UNINSTALLATION:
- Double-click "Uninstall Payroll Processor.command"
- Or manually delete from /Applications

For support, contact your system administrator.
EOF

# Add user agreement if present
if [ -f "$AGREEMENT_SOURCE" ]; then
    print_status "Adding user agreement..."
    cp "$AGREEMENT_SOURCE" "$AGREEMENT_TXT"
fi

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
    print_status "Creating DMG (drag-and-drop installer)..."
    
    # Create temporary DMG
    hdiutil create -size 150m -fs HFS+ -volname "Payroll Processor" "$RELEASE_ROOT/temp.dmg" > /dev/null 2>&1
    
    # Mount DMG
    hdiutil attach "$RELEASE_ROOT/temp.dmg" -mountpoint /tmp/payroll_dmg > /dev/null 2>&1
    
    # Copy app bundle
    cp -R "$REPO_ROOT/dist/Payroll Processor.app" /tmp/payroll_dmg/ 2>/dev/null
    # Copy documentation (README + agreement)
    cp "$INSTALLER_DIR/README.txt" /tmp/payroll_dmg/ 2>/dev/null
    if [ -f "$AGREEMENT_TXT" ]; then
        cp "$AGREEMENT_TXT" /tmp/payroll_dmg/ 2>/dev/null
    fi
    
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
echo ""
echo "🧩 Drag-and-drop DMG:"
echo "   • Open the DMG and drag Payroll Processor into Applications"

print_success "Installation package ready!"
