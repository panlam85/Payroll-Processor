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
import tempfile
from pathlib import Path
from typing import Optional
import sysconfig

APP_VERSION = "3.1.2"
APP_VERSION_SHORT = APP_VERSION.rsplit(".", 1)[0] if "." in APP_VERSION else APP_VERSION

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
VERSION_DIR = SCRIPT_DIR.parent
REPO_ROOT = VERSION_DIR.parent.parent
SRC_DIR = VERSION_DIR / "src"
RESOURCES_DIR = VERSION_DIR / "resources"
ASSETS_DIR = VERSION_DIR / "assets"
REQ_FILE = VERSION_DIR / "requirements.txt"
DIST_DIR = REPO_ROOT / "dist"
VENV_EMBED_DIR = VERSION_DIR / ".venv-embed"


def ensure_venv() -> Path:
    """Create or refresh a local venv for embedding."""
    cfg_path = VENV_EMBED_DIR / "pyvenv.cfg"
    if cfg_path.exists():
        cfg_text = cfg_path.read_text(encoding="utf-8")
        if str(VENV_EMBED_DIR) not in cfg_text:
            print("♻️  Recreating embedded venv (stale path detected)...")
            shutil.rmtree(VENV_EMBED_DIR)
    if not VENV_EMBED_DIR.exists():
        print("🐍 Creating embedded Python venv...")
        subprocess.check_call(["python3", "-m", "venv", "--copies", str(VENV_EMBED_DIR)])
    # Verify the venv python is runnable (avoid exec format errors)
    venv_python = VENV_EMBED_DIR / "bin" / "python"
    try:
        subprocess.check_call([str(venv_python), "-c", "import sys; print(sys.version)"])
    except Exception:
        print("♻️  Embedded venv appears invalid for this architecture; recreating...")
        shutil.rmtree(VENV_EMBED_DIR, ignore_errors=True)
        subprocess.check_call(["python3", "-m", "venv", "--copies", str(VENV_EMBED_DIR)])
        venv_python = VENV_EMBED_DIR / "bin" / "python"
    print("📦 Installing Python dependencies into embedded venv...")
    try:
        subprocess.check_call([str(venv_python), "-m", "pip", "--version"])
    except Exception:
        print("♻️  pip appears broken; bootstrapping with ensurepip...")
        subprocess.check_call([str(venv_python), "-m", "ensurepip", "--upgrade"])
    try:
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "-r", str(REQ_FILE)])
    except subprocess.CalledProcessError:
        print("♻️  pip failed; recreating embedded venv and retrying...")
        shutil.rmtree(VENV_EMBED_DIR, ignore_errors=True)
        subprocess.check_call(["python3", "-m", "venv", "--copies", str(VENV_EMBED_DIR)])
        venv_python = VENV_EMBED_DIR / "bin" / "python"
        subprocess.check_call([str(venv_python), "-m", "ensurepip", "--upgrade"])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        subprocess.check_call([str(venv_python), "-m", "pip", "install", "-r", str(REQ_FILE)])
    python_path = venv_python
    check_code = (
        "import importlib.util, sys; "
        "mods=['matplotlib','pandas','xlsxwriter','tkinterdnd2','psycopg2']; "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "sys.exit(','.join(missing) if missing else 0)"
    )
    try:
        subprocess.check_call([str(python_path), "-c", check_code])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Missing modules in embedded venv: {exc}") from exc
    return VENV_EMBED_DIR

def _venv_ignore(_path: str, names):
    ignored = set()
    for name in names:
        if name in {"__pycache__", ".pytest_cache", ".DS_Store"}:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo")):
            ignored.add(name)
    return ignored

def _copy_venv(src: Path, dst: Path, slim: bool = False) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    rsync_path = shutil.which("rsync")
    if rsync_path:
        print("📦 Copying embedded venv (this can take a few minutes)...")
        extra_excludes = []
        if slim:
            extra_excludes = [
                "--exclude=matplotlib/tests",
                "--exclude=matplotlib/mpl-data",
                "--exclude=numpy/tests",
                "--exclude=pandas/tests",
                "--exclude=pandas/_libs/tslibs/tests",
                "--exclude=*.dist-info/RECORD",
            ]
        try:
            subprocess.check_call(
                [
                    rsync_path,
                    "-a",
                    "--delete",
                    "--progress",
                    "--exclude=__pycache__",
                    "--exclude=.pytest_cache",
                    "--exclude=*.pyc",
                    "--exclude=*.pyo",
                    *extra_excludes,
                    f"{src}/",
                    str(dst),
                ]
            )
            return
        except subprocess.CalledProcessError:
            print("⚠️  rsync failed, falling back to copytree.")
    shutil.copytree(src, dst, symlinks=True, ignore=_venv_ignore)


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

def find_python_framework(python_bin: Path) -> Optional[Path]:
    """Locate the Python.framework used by the embedded Python."""
    try:
        output = subprocess.check_output(
            [
                str(python_bin),
                "-c",
                "import sysconfig; "
                "print(sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX') or '') ; "
                "print(sysconfig.get_config_var('PYTHONFRAMEWORK') or '') ; "
                "print(sysconfig.get_config_var('VERSION') or '')",
            ],
            text=True,
        ).splitlines()
        if len(output) >= 3:
            prefix = output[0].strip()
            framework = output[1].strip()
            version = output[2].strip()
            if prefix and framework and version:
                framework_path = Path(prefix) / f"{framework}.framework"
                if framework_path.exists():
                    return framework_path
    except Exception:
        return None
    return None

def patch_python_framework_link(python_bin: Path, framework_path: Path) -> None:
    """Rewrite the Python.framework load path to the bundled copy."""
    install_tool = shutil.which("install_name_tool")
    if not install_tool:
        print("⚠️  install_name_tool not available; skipping framework relink.")
        return
    version = sysconfig.get_config_var("VERSION") or ""
    if not version:
        try:
            version = subprocess.check_output(
                [str(python_bin), "-c", "import sysconfig; print(sysconfig.get_config_var('VERSION') or '')"],
                text=True,
            ).strip()
        except Exception:
            version = ""
    if not version:
        print("⚠️  Unable to determine Python framework version; skipping relink.")
        return
    old_path = str(framework_path / "Versions" / version / "Python")
    new_path = f"@executable_path/../../Python.framework/Versions/{version}/Python"
    try:
        subprocess.check_call([install_tool, "-change", old_path, new_path, str(python_bin)])
        print("✅ Relinked embedded Python to bundled framework.")
    except Exception as exc:
        print(f"⚠️  Failed to relink Python framework: {exc}")

def create_simple_app():
    """Create a simple app bundle without py2app."""
    
    print("🔧 Creating simple app bundle...")
    
    # Clean old builds
    if DIST_DIR.exists():
        def _on_rm_error(func, path, exc_info):
            try:
                os.chmod(path, stat.S_IRWXU)
                func(path)
            except Exception:
                pass

        try:
            os.chmod(DIST_DIR, stat.S_IRWXU)
        except Exception:
            pass
        shutil.rmtree(DIST_DIR, onerror=_on_rm_error)
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
    
    # Prepare bundle resources
    resources_dir = app_path / "Contents" / "Resources"
    icon_dest = resources_dir / "app_icon.icns"
    icon_generated = False
    app_icon_png = ASSETS_DIR / "app_icon.png"
    if app_icon_png.exists():
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                iconset = Path(tmp_dir) / "app_icon.iconset"
                iconset.mkdir(parents=True, exist_ok=True)
                base_sizes = [16, 32, 64, 128, 256, 512]
                for size in base_sizes:
                    subprocess.check_call([
                        "sips",
                        "-z", str(size), str(size),
                        str(app_icon_png),
                        "--out", str(iconset / f"icon_{size}x{size}.png"),
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.check_call([
                        "sips",
                        "-z", str(size * 2), str(size * 2),
                        str(app_icon_png),
                        "--out", str(iconset / f"icon_{size}x{size}@2x.png"),
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.check_call(
                    ["iconutil", "-c", "icns", str(iconset), "-o", str(icon_dest)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                icon_generated = True
        except Exception as exc:
            print(f"⚠️  Failed to generate app icon: {exc}")

    if not icon_generated:
        icon_path = RESOURCES_DIR / "app_icon.icns"
        if icon_path.exists():
            shutil.copy(icon_path, icon_dest)
    
    # Copy Python files
    for path in SRC_DIR.glob("*.py"):
        shutil.copy(path, resources_dir)
    shutil.copy(REQ_FILE, resources_dir)

    # Copy assets (logos, button icons)
    if ASSETS_DIR.exists():
        assets_dest = resources_dir / "assets"
        if assets_dest.exists():
            shutil.rmtree(assets_dest)
        shutil.copytree(ASSETS_DIR, assets_dest)

    # Embed Python venv
    venv_path = ensure_venv()
    embedded_venv = resources_dir / "venv"
    slim_env = os.environ.get("PAYROLL_SLIM_VENV", "").strip().lower()
    slim_mode = slim_env in {"1", "true", "yes", "on"}
    if slim_mode:
        print("⚡ Slim venv mode enabled (PAYROLL_SLIM_VENV=1)")
    _copy_venv(venv_path, embedded_venv, slim=slim_mode)

    # Bundle Python.framework for portability across machines
    embedded_python = embedded_venv / "bin" / "python"
    framework_path = find_python_framework(embedded_python)
    if framework_path:
        bundled_framework = resources_dir / "Python.framework"
        if bundled_framework.exists():
            shutil.rmtree(bundled_framework)
        print(f"📦 Bundling Python.framework from {framework_path}...")
        shutil.copytree(framework_path, bundled_framework, symlinks=True)
        patch_python_framework_link(embedded_python, framework_path)
    else:
        print("⚠️  Python.framework not found; app may require system Python.")

    # Embed poppler (pdftotext) if available
    poppler_prefix = find_poppler_prefix()
    if poppler_prefix:
        pdftotext_src = poppler_prefix / "bin" / "pdftotext"
        pdfseparate_src = poppler_prefix / "bin" / "pdfseparate"
        pdfunite_src = poppler_prefix / "bin" / "pdfunite"
        lib_src = poppler_prefix / "lib"
        bin_dest = resources_dir / "bin"
        lib_dest = resources_dir / "lib"
        bin_dest.mkdir(parents=True, exist_ok=True)
        lib_dest.mkdir(parents=True, exist_ok=True)
        if pdftotext_src.exists():
            shutil.copy(pdftotext_src, bin_dest / "pdftotext")
            os.chmod(bin_dest / "pdftotext", 0o755)
        if pdfseparate_src.exists():
            shutil.copy(pdfseparate_src, bin_dest / "pdfseparate")
            os.chmod(bin_dest / "pdfseparate", 0o755)
        if pdfunite_src.exists():
            shutil.copy(pdfunite_src, bin_dest / "pdfunite")
            os.chmod(bin_dest / "pdfunite", 0o755)
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
EMBED_LIB="$RESOURCES_DIR/lib"

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

if [ -d "$RESOURCES_DIR/Python.framework" ]; then
    PY_FRAMEWORK="$RESOURCES_DIR/Python.framework/Versions/Current"
    export DYLD_LIBRARY_PATH="$PY_FRAMEWORK:$DYLD_LIBRARY_PATH"
fi

export PYTHONPATH="$RESOURCES_DIR:$PYTHONPATH"

# Launch the GUI (capture output to a log so Finder launch errors are visible)
LOG_DIR="$HOME/Library/Logs/Payroll Processor"
LOG_FILE="$LOG_DIR/app.log"
mkdir -p "$LOG_DIR"

ARCH_BIN="/usr/bin/arch"
if [ -x "$ARCH_BIN" ]; then
    "$ARCH_BIN" -arm64 "$PYTHON_BIN" payroll_gui.py >>"$LOG_FILE" 2>&1
else
    "$PYTHON_BIN" payroll_gui.py >>"$LOG_FILE" 2>&1
fi
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    osascript -e 'display dialog "Payroll Processor closed unexpectedly. See log at:'$'\n''"$LOG_FILE"'" buttons {"OK"} default button "OK"'
fi
"""
    
    launcher_path = app_path / "Contents" / "MacOS" / "payroll_processor"
    with open(launcher_path, "w") as f:
        f.write(launcher_script)
    
    # Make launcher executable
    st = os.stat(launcher_path)
    os.chmod(launcher_path, st.st_mode | stat.S_IEXEC)
    
    # Sign app bundle (ad-hoc by default, or Developer ID if provided)
    sign_identity = os.environ.get("APPLE_CODESIGN_ID", "-")
    sign_cmd = ["codesign", "--force", "--deep", "--sign", sign_identity]
    if sign_identity != "-":
        sign_cmd += ["--options", "runtime", "--timestamp"]
    sign_cmd.append(str(app_path))
    try:
        subprocess.check_call(sign_cmd)
        if sign_identity == "-":
            print("✅ Ad-hoc signed app bundle.")
        else:
            print(f"✅ Signed app bundle with {sign_identity}.")
    except Exception as exc:
        print(f"⚠️  Signing failed: {exc}")

    print(f"✅ Simple app bundle created: {app_path}")
    print("📝 Note: This app embeds Python and pdftotext when available on the build machine.")
    
    return app_path

if __name__ == "__main__":
    create_simple_app()
