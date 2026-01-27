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

APP_VERSION="${APP_VERSION:-3.1.2}"
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

RELEASE_ROOT="$REPO_ROOT/releases/v${APP_VERSION}"
INSTALLER_DIR="$RELEASE_ROOT/PayrollProcessor_Installer"
ZIP_BASENAME="PayrollProcessor_v${APP_VERSION}_macOS.zip"
DMG_BASENAME="PayrollProcessor_v${APP_VERSION}_macOS.dmg"
AGREEMENT_SOURCE="$REPO_ROOT/user_agreement.md"
AGREEMENT_TXT="$INSTALLER_DIR/User Agreement.txt"
HOWTO_TXT="$INSTALLER_DIR/How to Install.txt"

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

# Sign the app bundle (ad-hoc by default, or Developer ID if provided)
if command -v codesign &> /dev/null; then
    SIGN_ID="${APPLE_CODESIGN_ID:--}"
    SIGN_CMD=(codesign --force --deep --sign "$SIGN_ID")
    if [ "$SIGN_ID" != "-" ]; then
        SIGN_CMD+=(--options runtime --timestamp)
    fi
    SIGN_CMD+=("$INSTALLER_DIR/Payroll Processor.app")
    if "${SIGN_CMD[@]}" >/dev/null 2>&1; then
        if [ "$SIGN_ID" = "-" ]; then
            print_status "Ad-hoc signed app bundle."
        else
            print_status "Signed app bundle with $SIGN_ID."
        fi
    else
        print_warning "Signing app bundle failed."
    fi
else
    print_warning "codesign not available; skipping app signing."
fi

# Create simple installer script
print_status "Creating installer script..."
cat > "$INSTALLER_DIR/Install Payroll Processor.command" << 'EOF'
#!/bin/bash
# Payroll Processor Simple Installer

echo "🔧 Installing Payroll Processor..."

# Get the directory where this script is located
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Payroll Processor.app"
SYSTEM_APPS="/Applications"
USER_APPS="$HOME/Applications"
DEST_DIR="$SYSTEM_APPS"

if [ ! -w "$SYSTEM_APPS" ]; then
    DEST_DIR="$USER_APPS"
    mkdir -p "$USER_APPS"
fi

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
echo "   $DEST_DIR/Payroll Processor.app"
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
USER_APP_PATH="$HOME/Applications/Payroll Processor.app"

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
    if [ -d "$USER_APP_PATH" ]; then
        read -p "Remove Payroll Processor from $HOME/Applications? (y/N): " confirm
        if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
            if rm -rf "$USER_APP_PATH"; then
                echo "✅ Payroll Processor has been removed."
            else
                echo "❌ Failed to remove application. You may need to remove it manually."
            fi
        else
            echo "❌ Uninstallation cancelled."
        fi
    else
        echo "ℹ️  Payroll Processor is not installed."
    fi
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
1. Launch "Payroll Processor" from /Applications (or ~/Applications if permissions require)
2. Drag and drop ZIP files containing Greek payroll PDFs
3. Click "Generate Reports" to create Excel files
4. Pick an output folder; reports are saved under an "Employees Reports" subfolder

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

# Create DMG how-to text (short, for the DMG window)
cat > "$HOWTO_TXT" << 'EOF'
How to install Payroll Processor
===============================
1. Drag "Payroll Processor.app" onto "Applications".
2. Launch it from Applications or Launchpad.

If macOS blocks the app:
- Right-click the app in Applications, choose Open, then confirm.
- On recent macOS versions: Apple menu → System Settings → Privacy & Security → Open Anyway.

Requires PostgreSQL installed and running.
Download: https://www.postgresql.org/download/macosx/
Alt download: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
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
    
    APP_SIZE_KB="$(du -sk "$INSTALLER_DIR/Payroll Processor.app" | awk '{print $1}')"
    EXTRA_MB=80
    SIZE_MB=$(( (APP_SIZE_KB / 1024) + EXTRA_MB ))
    if [ "$SIZE_MB" -lt 200 ]; then
        SIZE_MB=200
    fi
    
    # Create temporary DMG
    rm -f "$RELEASE_ROOT/temp.dmg"
    CREATE_OUTPUT="$(hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname "Payroll Processor" "$RELEASE_ROOT/temp.dmg" 2>&1)"
    if [ $? -ne 0 ]; then
        print_error "Failed to create temporary DMG."
        echo "$CREATE_OUTPUT"
        exit 1
    fi
    
    # Mount DMG
    hdiutil detach /tmp/payroll_dmg > /dev/null 2>&1 || true
    rm -rf /tmp/payroll_dmg
    mkdir -p /tmp/payroll_dmg
    ATTACH_OUTPUT="$(hdiutil attach "$RELEASE_ROOT/temp.dmg" -mountpoint /tmp/payroll_dmg -nobrowse -noverify -noautoopen 2>&1)"
    if [ $? -ne 0 ]; then
        print_error "Failed to mount DMG at /tmp/payroll_dmg."
        echo "$ATTACH_OUTPUT"
        rm -f "$RELEASE_ROOT/temp.dmg"
        exit 1
    fi
    DMG_DEVICE="$(echo "$ATTACH_OUTPUT" | awk 'NR==1 {print $1}')"
    
    # Copy app bundle
    if ! ditto "$INSTALLER_DIR/Payroll Processor.app" "/tmp/payroll_dmg/Payroll Processor.app" 2>/dev/null; then
        print_error "Failed to copy app bundle into DMG (insufficient space?)."
        hdiutil detach /tmp/payroll_dmg > /dev/null 2>&1 || true
        rm -f "$RELEASE_ROOT/temp.dmg"
        exit 1
    fi
    # Copy how-to text for the DMG window
    if ! cp "$HOWTO_TXT" /tmp/payroll_dmg/ 2>/dev/null; then
        print_error "Failed to copy How to Install.txt into DMG."
        hdiutil detach /tmp/payroll_dmg > /dev/null 2>&1 || true
        rm -f "$RELEASE_ROOT/temp.dmg"
        exit 1
    fi
    
    # Create Applications alias (Finder alias, not a symlink)
    if command -v osascript &> /dev/null; then
        if ! osascript << 'EOF' >/dev/null 2>&1
tell application "Finder"
    set dmgFolder to POSIX file "/tmp/payroll_dmg" as alias
    set appFolder to POSIX file "/Applications" as alias
    set theAlias to make new alias file to appFolder at dmgFolder
    set name of theAlias to "Applications"
end tell
EOF
        then
            ln -s /Applications /tmp/payroll_dmg/Applications 2>/dev/null
        fi
    else
        ln -s /Applications /tmp/payroll_dmg/Applications 2>/dev/null
    fi

    # Arrange Finder window to fit just 3 items
    if command -v osascript &> /dev/null; then
        osascript << 'EOF' >/dev/null 2>&1
tell application "Finder"
    set dmgFolder to POSIX file "/tmp/payroll_dmg" as alias
    set dmgWindow to container window of dmgFolder
    open dmgFolder
    set current view of dmgWindow to icon view
    set toolbar visible of dmgWindow to false
    set statusbar visible of dmgWindow to false
    set the bounds of dmgWindow to {100, 100, 520, 360}
    set icon size of icon view options of dmgWindow to 96
    set arrangement of icon view options of dmgWindow to not arranged
    set position of item "Payroll Processor.app" of dmgFolder to {130, 120}
    set position of item "Applications" of dmgFolder to {360, 120}
    set position of item "How to Install.txt" of dmgFolder to {245, 240}
    close dmgWindow
    delay 1
    open dmgFolder
    update without registering applications
end tell
EOF
    fi
    
    # Unmount and convert to read-only
    sync
    if [ -n "$DMG_DEVICE" ]; then
    hdiutil detach "$DMG_DEVICE" > /dev/null 2>&1
    else
        hdiutil detach /tmp/payroll_dmg > /dev/null 2>&1
    fi
    rm -f "$RELEASE_ROOT/$DMG_BASENAME"
    hdiutil convert "$RELEASE_ROOT/temp.dmg" -format UDZO -ov -o "$RELEASE_ROOT/$DMG_BASENAME" > /dev/null 2>&1
    rm -f "$RELEASE_ROOT/temp.dmg"
    
    if [ -f "$RELEASE_ROOT/$DMG_BASENAME" ]; then
        print_success "DMG installer created: releases/v${APP_VERSION}/$DMG_BASENAME"
        if command -v xcrun &> /dev/null && xcrun notarytool --help >/dev/null 2>&1; then
            if [ -n "$APPLE_NOTARY_KEYCHAIN_PROFILE" ]; then
                print_status "Submitting DMG for notarization..."
                if xcrun notarytool submit "$RELEASE_ROOT/$DMG_BASENAME" --keychain-profile "$APPLE_NOTARY_KEYCHAIN_PROFILE" --wait; then
                    print_status "Stapling notarization ticket to DMG..."
                    xcrun stapler staple "$RELEASE_ROOT/$DMG_BASENAME" >/dev/null 2>&1 || true
                else
                    print_warning "Notarization failed."
                fi
            else
                print_warning "APPLE_NOTARY_KEYCHAIN_PROFILE not set; skipping notarization."
            fi
        fi
    fi
fi

print_success "Installer package created successfully!"
echo ""
echo "📦 Available packages:"
echo "   • releases/v${APP_VERSION}/PayrollProcessor_Installer/"
echo "   • releases/v${APP_VERSION}/$ZIP_BASENAME"
if [ -f "$RELEASE_ROOT/$DMG_BASENAME" ]; then
    echo "   • releases/v${APP_VERSION}/$DMG_BASENAME"
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
