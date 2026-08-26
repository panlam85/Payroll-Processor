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

def _detect_app_version(default: str = "3.1.7") -> str:
    """Derive the version from the versions/vX.Y.Z directory holding this script.

    A hardcoded literal here drifted to 3.1.3 while the tree moved to 3.1.4, so
    the bundle advertised the wrong version in its Info.plist and About dialog.
    """
    name = Path(__file__).resolve().parent.parent.name
    if name.startswith("v") and all(part.isdigit() for part in name[1:].split(".")):
        return name[1:]
    return default


APP_VERSION = _detect_app_version()
APP_VERSION_SHORT = APP_VERSION

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
ARCH_BIN = shutil.which("arch")
LIPO_BIN = shutil.which("lipo")

BUILD_PYTHON_ENV = "PAYROLL_BUILD_PYTHON"
_BASE_PYTHON: Optional[str] = None

BUILD_PYTHON_HELP = f"""No usable Python found for building the app bundle.

The embedded venv must be created with --copies so the .app is self-contained.
Apple's stub python3 (the one shipped with Xcode / Command Line Tools) refuses:
    "This build of python cannot create venvs without using symlinks"
and its framework lives inside Xcode.app, so a symlinked venv would break on
any other machine anyway.

Install a real Python, then re-run this script:
  * python.org universal2 installer (best - builds arm64 + x86_64 in one .app):
        https://www.python.org/downloads/macos/
  * or Homebrew (single-arch build only):
        brew install python@3.12

Or point the build at a specific interpreter:
        {BUILD_PYTHON_ENV}=/path/to/python3 ./create_simple_app.py
"""


class BuildPythonError(RuntimeError):
    """Raised when no interpreter capable of building the bundle is available."""


def _supports_copies(python_bin: str) -> bool:
    """Check that an interpreter can create a copied venv and run the Tk GUI."""
    try:
        subprocess.check_call(
            [python_bin, "-c", "import tkinter"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe"
        try:
            subprocess.check_call(
                [python_bin, "-m", "venv", "--copies", "--without-pip", str(probe)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
    return True


def _base_python_candidates():
    override = os.environ.get(BUILD_PYTHON_ENV, "").strip()
    if override:
        return [override]
    candidates = []
    for version in ("3.13", "3.12", "3.11", "3.10"):
        candidates.append(f"/Library/Frameworks/Python.framework/Versions/{version}/bin/python3")
        # Homebrew ships only the versioned name (python3.12) in its opt prefix -
        # there is no bare python3 there, so check both spellings.
        candidates.append(f"/opt/homebrew/opt/python@{version}/bin/python{version}")
        candidates.append(f"/opt/homebrew/opt/python@{version}/bin/python3")
        candidates.append(f"/usr/local/opt/python@{version}/bin/python{version}")
        candidates.append(f"/usr/local/opt/python@{version}/bin/python3")
    path_python = shutil.which("python3")
    if path_python:
        candidates.append(path_python)
    return candidates


def base_python() -> str:
    """Pick an interpreter that can build a self-contained embedded venv."""
    global _BASE_PYTHON
    if _BASE_PYTHON:
        return _BASE_PYTHON
    seen = []
    for candidate in _base_python_candidates():
        resolved = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if not resolved or resolved in seen:
            continue
        seen.append(resolved)
        if _supports_copies(resolved):
            _BASE_PYTHON = resolved
            print(f"🐍 Using base Python: {resolved}")
            return resolved
        print(f"⚠️  {resolved} cannot create self-contained venvs (--copies unsupported); skipping.")
    raise BuildPythonError(BUILD_PYTHON_HELP)


def _venv_dir_for_arch(target_arch: Optional[str]) -> Path:
    if not target_arch:
        return VENV_EMBED_DIR / "default"
    return VENV_EMBED_DIR / target_arch


def _run_python(python_bin: Path, args, target_arch: Optional[str] = None) -> None:
    cmd = [str(python_bin), *args]
    if target_arch and ARCH_BIN:
        cmd = [ARCH_BIN, f"-{target_arch}", str(python_bin), *args]
    subprocess.check_call(cmd)


def _create_venv(venv_dir: Path, target_arch: Optional[str]) -> None:
    python_bin = base_python()
    python_cmd = [python_bin, "-m", "venv", "--copies", str(venv_dir)]
    if target_arch and ARCH_BIN:
        python_cmd = [ARCH_BIN, f"-{target_arch}", python_bin, "-m", "venv", "--copies", str(venv_dir)]
    subprocess.check_call(python_cmd)


def ensure_venv(target_arch: Optional[str] = None) -> Path:
    """Create or refresh a local venv for embedding."""
    venv_dir = _venv_dir_for_arch(target_arch)
    cfg_path = venv_dir / "pyvenv.cfg"
    if cfg_path.exists():
        cfg_text = cfg_path.read_text(encoding="utf-8")
        if str(venv_dir) not in cfg_text:
            print("♻️  Recreating embedded venv (stale path detected)...")
            shutil.rmtree(venv_dir)
    if not venv_dir.exists():
        print(f"🐍 Creating embedded Python venv{f' ({target_arch})' if target_arch else ''}...")
        _create_venv(venv_dir, target_arch)
    # Verify the venv python is runnable (avoid exec format errors)
    venv_python = venv_dir / "bin" / "python"
    try:
        _run_python(venv_python, ["-c", "import sys; print(sys.version)"], target_arch)
    except Exception:
        print("♻️  Embedded venv appears invalid for this architecture; recreating...")
        shutil.rmtree(venv_dir, ignore_errors=True)
        _create_venv(venv_dir, target_arch)
        venv_python = venv_dir / "bin" / "python"
    print("📦 Installing Python dependencies into embedded venv...")
    try:
        _run_python(venv_python, ["-m", "pip", "--version"], target_arch)
    except Exception:
        print("♻️  pip appears broken; bootstrapping with ensurepip...")
        _run_python(venv_python, ["-m", "ensurepip", "--upgrade"], target_arch)
    try:
        _run_python(venv_python, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], target_arch)
        _run_python(venv_python, ["-m", "pip", "install", "-r", str(REQ_FILE)], target_arch)
    except subprocess.CalledProcessError:
        print("♻️  pip failed; recreating embedded venv and retrying...")
        shutil.rmtree(venv_dir, ignore_errors=True)
        _create_venv(venv_dir, target_arch)
        venv_python = venv_dir / "bin" / "python"
        _run_python(venv_python, ["-m", "ensurepip", "--upgrade"], target_arch)
        _run_python(venv_python, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], target_arch)
        _run_python(venv_python, ["-m", "pip", "install", "-r", str(REQ_FILE)], target_arch)
    python_path = venv_python
    check_code = (
        "import importlib.util, sys; "
        "mods=['matplotlib','pandas','xlsxwriter','tkinterdnd2','psycopg2']; "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "sys.exit(','.join(missing) if missing else 0)"
    )
    try:
        _run_python(python_path, ["-c", check_code], target_arch)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Missing modules in embedded venv: {exc}") from exc
    return venv_dir

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
    ditto_bin = shutil.which("ditto")
    if ditto_bin:
        subprocess.check_call([ditto_bin, "--norsrc", str(src), str(dst)])
    else:
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

def _python_framework_version(python_bin: Path) -> str:
    # Ask the *embedded* interpreter, not the one running this script. The build
    # script may run under a different Python (e.g. Apple's 3.9 via the shebang)
    # than the one being bundled, and a wrong version here silently breaks the
    # relink filter and makes the verification pass without checking anything.
    try:
        version = subprocess.check_output(
            [str(python_bin), "-c", "import sysconfig; print(sysconfig.get_config_var('VERSION') or '')"],
            text=True,
        ).strip()
    except Exception:
        version = ""
    # Deliberately no fallback to this script's own sysconfig: the build may run
    # under a different Python, and a wrong version silently relinks the bundle
    # to a framework directory that does not exist. Empty means "unknown".
    return version


def _framework_version_from_path(framework: Path) -> str:
    """Read the version from a framework's Versions/ directory.

    Preferred over probing the embedded interpreter, which becomes unrunnable
    the moment install_name_tool invalidates its signature on Apple Silicon.
    """
    versions = framework / "Versions"
    if not versions.is_dir():
        return ""
    names = [
        p.name
        for p in versions.iterdir()
        if p.is_dir() and p.name != "Current" and p.name[:1].isdigit()
    ]
    return sorted(names)[-1] if names else ""


def _relink_binary(binary: Path, old_path: Path, target_python: Path) -> bool:
    install_tool = shutil.which("install_name_tool")
    if not install_tool or not binary.exists():
        return False
    try:
        rel = os.path.relpath(target_python, binary.parent)
        new_path = f"@executable_path/{rel}"
        subprocess.check_call([install_tool, "-change", str(old_path), new_path, str(binary)])
        return True
    except Exception:
        return False


def _is_macho(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
    except Exception:
        return False
    # thin little/big endian, 64-bit, and universal (fat) magics
    return magic in {
        b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    }


def _bundled_python_dependency_target(dep: str, bundled_framework: Path) -> Optional[Path]:
    """Map an absolute Python.framework dependency to its bundled counterpart."""
    marker = "Python.framework/"
    if not dep.startswith("/") or marker not in dep:
        return None
    relative = dep.split(marker, 1)[1]
    if not relative:
        return None
    return bundled_framework / Path(relative)


def relink_bundle_python_refs(search_roots, bundled_framework: Path, version: str) -> int:
    """Point every Mach-O in the bundle at the embedded framework.

    A --copies venv contains several real python binaries (python, python3,
    python3.X), not just one, and the framework dylib carries its own absolute
    install name. Relinking a hardcoded subset leaves the rest tied to the build
    machine, so walk everything and rewrite any absolute Python.framework
    reference. Returns the number of binaries changed.
    """
    install_tool = shutil.which("install_name_tool")
    otool = shutil.which("otool")
    if not install_tool or not otool:
        print("⚠️  install_name_tool/otool not available; skipping bundle relink.")
        return 0
    target_python = bundled_framework / "Versions" / version / "Python"
    changed = 0
    seen = set()
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            # Resolve first and dedupe by real path: the same dylib is reachable
            # via Versions/Current and via Versions/<X.Y>, and skipping anything
            # symlinked would drop it entirely depending on which the walk sees.
            try:
                path = candidate.resolve()
            except Exception:
                continue
            if path in seen:
                continue
            seen.add(path)
            if not path.is_file() or not _is_macho(path):
                continue
            try:
                output = subprocess.check_output([otool, "-L", str(path)], text=True)
            except Exception:
                continue
            lines = output.splitlines()
            edits = []
            for line in lines[1:]:
                dep = line.strip().split(" ", 1)[0]
                bundled_target = _bundled_python_dependency_target(dep, bundled_framework)
                if bundled_target is None:
                    continue
                rel = os.path.relpath(bundled_target, path.parent)
                new_path = f"@loader_path/{rel}"
                try:
                    is_identity = path.resolve() == bundled_target.resolve()
                except Exception:
                    is_identity = False
                edits.append(["-id", new_path] if is_identity else ["-change", dep, new_path])
            if not edits:
                continue
            ok = False
            for edit in edits:
                try:
                    subprocess.check_call(
                        [install_tool, *edit, str(path)],
                        stderr=subprocess.DEVNULL,
                    )
                    ok = True
                except Exception:
                    continue
            if ok:
                # Re-sign immediately: install_name_tool invalidates the code
                # signature, and arm64 refuses to execute a binary whose
                # signature does not match. Without this the embedded Python is
                # silently unrunnable.
                _codesign_target(path)
                changed += 1
    if changed:
        print(f"🔗 Relinked and re-signed {changed} bundled binaries.")
    return changed


def _brand_framework_python_app(framework: Path, app_name: str) -> None:
    """Rename the framework's nested Python.app so the menu bar reads correctly.

    The launcher executes Python.framework/.../Resources/Python.app, and macOS
    takes the application menu title from the Info.plist of whichever bundle owns
    the running executable - so the menu said "Python" no matter what the outer
    bundle or tk appname claimed. This copy of the framework is private to the
    app, so renaming it here is safe and does not touch the system Python.
    """
    for plist_path in framework.rglob("Python.app/Contents/Info.plist"):
        try:
            with open(plist_path, "rb") as handle:
                data = plistlib.load(handle)
            data["CFBundleName"] = app_name
            data["CFBundleDisplayName"] = app_name
            with open(plist_path, "wb") as handle:
                plistlib.dump(data, handle)
            print(f"🏷️  Renamed nested Python.app to '{app_name}' for the menu bar.")
        except Exception as exc:
            print(f"⚠️  Could not rebrand {plist_path}: {exc}")


def _normalize_framework_layout(framework: Path) -> None:
    """Add the symlinks macOS expects of a versioned framework bundle.

    Homebrew's Python.framework ships only Versions/<X.Y> - no Versions/Current
    and no top-level Python/Resources aliases. codesign rejects that layout with
    "bundle format unrecognized, invalid, or unsuitable", so recreate the
    canonical links before signing. python.org frameworks already have them and
    are left untouched.
    """
    versions = framework / "Versions"
    if not versions.is_dir():
        return
    concrete = sorted(
        (p for p in versions.iterdir() if p.is_dir() and not p.is_symlink() and p.name != "Current"),
        key=lambda p: p.name,
    )
    if not concrete:
        return
    current = versions / "Current"
    if not current.exists() and not current.is_symlink():
        current.symlink_to(concrete[-1].name)
    for name in ("Python", "Resources", "Headers"):
        link = framework / name
        if link.exists() or link.is_symlink():
            continue
        if (versions / "Current" / name).exists():
            link.symlink_to(Path("Versions") / "Current" / name)
    # Homebrew points lib/pythonX.Y/site-packages at its own prefix, so the copy
    # inside the bundle dangles. A dangling link both breaks `codesign --deep
    # --strict` ("No such file or directory") and leaves the app referring to a
    # path off the machine. The embedded venv supplies site-packages, so an empty
    # directory is a safe stand-in; anything else dangling is simply dropped.
    pruned = 0
    for link in framework.rglob("*"):
        if not link.is_symlink() or link.exists():
            continue
        try:
            if link.name == "site-packages":
                link.unlink()
                link.mkdir()
            else:
                link.unlink()
            pruned += 1
        except OSError:
            continue
    # Static archives and build configuration scripts are not used at runtime.
    # Leaving them inside a nested framework makes codesign treat some as
    # unsigned subcomponents, so omit that development-only payload.
    removed_build_files = 0
    for pattern in ("*.a", "*Config.sh"):
        for build_file in framework.rglob(pattern):
            try:
                build_file.unlink()
                removed_build_files += 1
            except OSError:
                continue
    if removed_build_files:
        print(f"🧹 Removed {removed_build_files} framework build-only file(s).")
    if pruned:
        print(f"🧹 Pruned {pruned} dangling symlink(s) from the bundled framework.")
    print("🔗 Normalized Python.framework layout (Versions/Current + aliases).")


def _verify_python_framework_links(binaries, framework_prefix: str) -> bool:
    """Fail if any binary still loads Python.framework from outside the bundle.

    Checking one hardcoded prefix is not enough: a build from Homebrew (or any
    non-system Python) references a different absolute path, so a prefix-only
    check passes while the bundle is still tied to this machine. Any absolute
    Python.framework dependency is disqualifying - inside the bundle the load
    path must be @executable_path/@loader_path/@rpath relative.
    """
    otool = shutil.which("otool")
    if not otool:
        print("⚠️  otool not available; skipping framework link verification.")
        return True
    bad = {}
    checked = 0
    for binary in binaries:
        if not binary.exists():
            continue
        try:
            output = subprocess.check_output([otool, "-L", str(binary)], text=True)
        except Exception:
            continue
        checked += 1
        for line in output.splitlines()[1:]:
            dep = line.strip().split(" ", 1)[0]
            if not dep.startswith("/"):
                continue
            if framework_prefix in dep or "Python.framework" in dep:
                bad.setdefault(binary, []).append(dep)
    if bad:
        print("⚠️  Detected Python framework links outside the bundle:")
        for binary, deps in bad.items():
            for dep in deps:
                print(f"   - {binary}: {dep}")
        return False
    if not checked:
        # Nothing was inspected, so nothing was proven. Treat as a failure rather
        # than printing a checkmark that means only "no binaries were found".
        print("⚠️  No Python binaries were available to verify; cannot confirm self-containment.")
        return False
    print(f"✅ Verified bundled Python framework links ({checked} binaries checked).")
    return True


def _iter_executables(root: Path):
    if not root.exists():
        return []
    results = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            mode = path.stat().st_mode
        except Exception:
            continue
        if mode & stat.S_IXUSR:
            results.append(path)
    return results


def patch_python_framework_links(python_bins, framework_path: Path, bundled_framework: Path) -> None:
    """Rewrite Python.framework load paths to the bundled copy."""
    install_tool = shutil.which("install_name_tool")
    otool = shutil.which("otool")
    if not install_tool or not otool:
        print("⚠️  install_name_tool/otool not available; skipping framework relink.")
        return
    version = ""
    for candidate in python_bins:
        if candidate.exists():
            version = _python_framework_version(candidate)
            if version:
                break
    if not version:
        print("⚠️  Unable to determine Python framework version; skipping relink.")
        return
    old_path = str(framework_path / "Versions" / version / "Python")
    target_python = bundled_framework / "Versions" / version / "Python"
    relinked = False
    binaries = []
    binaries.extend([p for p in python_bins if p.exists()])
    binaries.extend(_iter_executables(bundled_framework / "Versions" / version / "Resources" / "Python.app"))
    binaries.extend(_iter_executables(bundled_framework / "Versions" / version / "bin"))
    for binary in binaries:
        try:
            output = subprocess.check_output([otool, "-L", str(binary)], text=True)
        except Exception:
            continue
        for line in output.splitlines():
            dep = line.strip().split(" ", 1)[0]
            if f"Python.framework/Versions/{version}/Python" not in dep:
                continue
            rel = os.path.relpath(target_python, binary.parent)
            new_path = f"@executable_path/{rel}"
            try:
                subprocess.check_call([install_tool, "-change", dep, new_path, str(binary)])
                relinked = True
            except Exception:
                continue
    if relinked:
        print("✅ Relinked Python binaries to bundled framework.")
    else:
        print("⚠️  No Python binaries relinked; app may require system Python.")

def _codesign_target(target: Path) -> None:
    codesign = shutil.which("codesign")
    if not codesign or not target.exists():
        return
    try:
        subprocess.check_call([codesign, "--force", "--sign", "-", str(target)])
    except Exception as exc:
        print(f"⚠️  Failed to codesign {target}: {exc}")

def _codesign_bundle(target: Path) -> None:
    codesign = shutil.which("codesign")
    if not codesign or not target.exists():
        return
    try:
        subprocess.check_call([codesign, "--force", "--deep", "--sign", "-", str(target)])
    except Exception as exc:
        print(f"⚠️  Failed to codesign bundle {target}: {exc}")

def _sign_embedded_code(app_path: Path) -> None:
    """Sign every embedded binary, deepest first, after all mutation is done.

    codesign --deep does not reliably reach nested bundles (Apple deprecates it
    for signing), which left the framework's inner Python.app unsigned after
    install_name_tool had rewritten it. macOS then killed the process with
    CODESIGNING / Invalid Page. Signing explicitly, innermost outwards, is the
    supported way to do this.
    """
    resources = app_path / "Contents" / "Resources"
    frameworks = app_path / "Contents" / "Frameworks"
    roots = [p for p in (resources, frameworks) if p.exists()]
    if not roots:
        return
    macho = []
    nested_bundles = []
    seen = set()
    for candidate in [c for root in roots for c in root.rglob("*")]:
        try:
            real = candidate.resolve()
        except Exception:
            continue
        if real in seen:
            continue
        seen.add(real)
        if real.is_dir() and real.suffix == ".app":
            nested_bundles.append(real)
        elif real.is_file() and _is_macho(real):
            macho.append(real)
    # Deepest paths first so a container is never signed before its contents.
    for target in sorted(macho, key=lambda p: len(p.parts), reverse=True):
        _codesign_target(target)
    for target in sorted(nested_bundles, key=lambda p: len(p.parts), reverse=True):
        _codesign_target(target)
    for framework in (frameworks / "Python.framework", resources / "Python.framework"):
        if framework.exists():
            _codesign_target(framework)
    print(f"🔏 Signed {len(macho)} embedded binaries and {len(nested_bundles)} nested bundles.")


def _strip_resource_forks_with_ditto(app_path: Path) -> None:
    ditto_bin = shutil.which("ditto")
    if not ditto_bin or not app_path.exists():
        return
    tmp_path = app_path.with_name(app_path.name + ".clean")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    try:
        subprocess.check_call([ditto_bin, "--norsrc", str(app_path), str(tmp_path)])
        shutil.rmtree(app_path)
        tmp_path.rename(app_path)
    except Exception as exc:
        print(f"⚠️  Failed to strip resource forks: {exc}")
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)

def _sanitize_bundle(app_path: Path) -> None:
    chmod_bin = shutil.which("chmod")
    xattr_bin = shutil.which("xattr")
    dot_clean_bin = shutil.which("dot_clean")
    find_bin = shutil.which("find")
    if chmod_bin:
        try:
            subprocess.check_call([chmod_bin, "-R", "u+w", str(app_path)])
        except Exception as exc:
            print(f"⚠️  Failed to chmod bundle: {exc}")
    if find_bin:
        try:
            subprocess.check_call([find_bin, str(app_path), "-name", "._*", "-delete"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call([find_bin, str(app_path), "-name", ".DS_Store", "-delete"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    if xattr_bin:
        try:
            subprocess.check_call([xattr_bin, "-dr", "com.apple.provenance", str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call([xattr_bin, "-cr", str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            # xattr may fail on broken symlinks inside frameworks; ignore and continue.
            try:
                for path in app_path.rglob("*"):
                    subprocess.call([xattr_bin, "-d", "com.apple.provenance", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.call([xattr_bin, "-cr", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
    if dot_clean_bin:
        try:
            subprocess.check_call([dot_clean_bin, "-m", str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def create_simple_app():
    """Create a simple app bundle without py2app."""

    print("🔧 Creating simple app bundle...")
    os.environ["COPYFILE_DISABLE"] = "1"

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
    (resources_dir / "APP_VERSION").write_text(f"{APP_VERSION}\n", encoding="utf-8")

    # Copy assets (logos, button icons)
    if ASSETS_DIR.exists():
        assets_dest = resources_dir / "assets"
        if assets_dest.exists():
            shutil.rmtree(assets_dest)
        shutil.copytree(ASSETS_DIR, assets_dest)

    # Embed Python venv(s)
    slim_env = os.environ.get("PAYROLL_SLIM_VENV", "").strip().lower()
    slim_mode = slim_env in {"1", "true", "yes", "on"}
    if slim_mode:
        print("⚡ Slim venv mode enabled (PAYROLL_SLIM_VENV=1)")

    venvs_to_embed = []
    try:
        python3_path = base_python()
    except BuildPythonError as exc:
        raise SystemExit(f"❌ {exc}") from None
    if ARCH_BIN and LIPO_BIN:
        lipo_info = ""
        try:
            lipo_info = subprocess.check_output([LIPO_BIN, "-info", python3_path], text=True).strip()
        except Exception:
            lipo_info = ""
        for arch in ("arm64", "x86_64"):
            if arch in lipo_info:
                try:
                    venvs_to_embed.append((arch, ensure_venv(arch)))
                except Exception as exc:
                    print(f"⚠️  Failed to build {arch} venv: {exc}")

    if not venvs_to_embed:
        venvs_to_embed.append((None, ensure_venv()))

    for arch, venv_path in venvs_to_embed:
        if arch:
            embedded_venv = resources_dir / f"venv-{arch}"
        else:
            embedded_venv = resources_dir / "venv"
        _copy_venv(venv_path, embedded_venv, slim=slim_mode)

    # Bundle Python.framework for portability across machines
    embedded_python = (resources_dir / "venv-arm64" / "bin" / "python")
    if not embedded_python.exists():
        embedded_python = (resources_dir / "venv-x86_64" / "bin" / "python")
    if not embedded_python.exists():
        embedded_python = (resources_dir / "venv" / "bin" / "python")
    framework_path = find_python_framework(embedded_python)
    if framework_path:
        # Nested code belongs in Contents/Frameworks. Under Contents/Resources
        # codesign seals the framework as a resource rather than as code, so the
        # bundle signature never validates ("a sealed resource is missing or
        # invalid") even though every binary inside it is correctly signed.
        frameworks_dir = app_path / "Contents" / "Frameworks"
        frameworks_dir.mkdir(parents=True, exist_ok=True)
        bundled_framework = frameworks_dir / "Python.framework"
        if bundled_framework.exists():
            shutil.rmtree(bundled_framework)
        legacy_framework = resources_dir / "Python.framework"
        if legacy_framework.exists():
            shutil.rmtree(legacy_framework)
        print(f"📦 Bundling Python.framework from {framework_path}...")
        ditto_bin = shutil.which("ditto")
        if ditto_bin:
            subprocess.check_call([ditto_bin, "--norsrc", str(framework_path), str(bundled_framework)])
        else:
            shutil.copytree(framework_path, bundled_framework, symlinks=True)
        _normalize_framework_layout(bundled_framework)
        _brand_framework_python_app(bundled_framework, "Payroll Processor")
        python_bins = [
            resources_dir / "venv" / "bin" / "python",
            resources_dir / "venv-arm64" / "bin" / "python",
            resources_dir / "venv-x86_64" / "bin" / "python",
        ]
        # Resolve the version BEFORE relinking. Afterwards the embedded
        # interpreter cannot be executed (install_name_tool breaks its
        # signature), so probing it would fail and yield a wrong version.
        version = _framework_version_from_path(framework_path) or _python_framework_version(embedded_python)
        if not version:
            raise RuntimeError(f"Could not determine Python framework version from {framework_path}")
        patch_python_framework_links(python_bins, framework_path, bundled_framework)
        # Sweep every Mach-O in the bundle. The list above misses the sibling
        # python3/python3.X copies and the framework's own install name, each of
        # which would keep the app bound to this build machine.
        relink_roots = [
            resources_dir / "venv",
            resources_dir / "venv-arm64",
            resources_dir / "venv-x86_64",
            bundled_framework,
        ]
        if version:
            relink_bundle_python_refs(relink_roots, bundled_framework, version)
        # Verify against the same exhaustive set, so a pass means the whole
        # bundle was inspected rather than one hand-picked binary.
        verify_bins = []
        _seen_verify = set()
        for root in relink_roots:
            if not root.exists():
                continue
            for candidate in root.rglob("*"):
                try:
                    real = candidate.resolve()
                except Exception:
                    continue
                if real in _seen_verify:
                    continue
                _seen_verify.add(real)
                if real.is_file() and _is_macho(real):
                    verify_bins.append(real)
        if not _verify_python_framework_links(verify_bins, "/Library/Frameworks/Python.framework"):
            raise RuntimeError("Embedded Python still references an external Python.framework")

        _codesign_bundle(bundled_framework)
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
    launcher_script = """#!/bin/bash
# Payroll Processor Launcher

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOURCES_DIR="$SCRIPT_DIR/../Resources"

# Change to resources directory
cd "$RESOURCES_DIR"

EMBED_VENV_ARM="$RESOURCES_DIR/venv-arm64"
EMBED_VENV_X64="$RESOURCES_DIR/venv-x86_64"
EMBED_VENV="$RESOURCES_DIR/venv"
EMBED_BIN="$RESOURCES_DIR/bin"
EMBED_LIB="$RESOURCES_DIR/lib"

PYTHON_BIN=""
PYTHON_ARCH=""
if [ -d "$EMBED_VENV_ARM" ] || [ -d "$EMBED_VENV_X64" ]; then
    if [ -x "/usr/sbin/sysctl" ] && [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
        if [ -d "$EMBED_VENV_ARM" ]; then
            PYTHON_BIN="$EMBED_VENV_ARM/bin/python"
            PYTHON_ARCH="arm64"
        elif [ -d "$EMBED_VENV_X64" ]; then
            PYTHON_BIN="$EMBED_VENV_X64/bin/python"
            PYTHON_ARCH="x86_64"
        fi
    else
        if [ -d "$EMBED_VENV_X64" ]; then
            PYTHON_BIN="$EMBED_VENV_X64/bin/python"
            PYTHON_ARCH="x86_64"
        elif [ -d "$EMBED_VENV_ARM" ]; then
            PYTHON_BIN="$EMBED_VENV_ARM/bin/python"
            PYTHON_ARCH="arm64"
        fi
    fi
elif [ -d "$EMBED_VENV" ]; then
    PYTHON_BIN="$EMBED_VENV/bin/python"
else
    /usr/bin/osascript <<EOF
display dialog "Embedded Python not found. Please rebuild the app." buttons {"OK"} default button "OK"
EOF
    exit 1
fi

if [ -x "$EMBED_BIN/pdftotext" ]; then
    PATH="$EMBED_BIN:$PATH"
    if [ -d "$EMBED_LIB" ]; then
        export DYLD_LIBRARY_PATH="$EMBED_LIB:$DYLD_LIBRARY_PATH"
    fi
fi

# Contents/Frameworks is where the framework now lives; the Resources path is
# kept as a fallback so an older bundle layout still launches.
FRAMEWORKS_DIR="$SCRIPT_DIR/../Frameworks"
if [ -d "$FRAMEWORKS_DIR/Python.framework" ]; then
    PY_FRAMEWORK="$FRAMEWORKS_DIR/Python.framework/Versions/Current"
    export DYLD_LIBRARY_PATH="$PY_FRAMEWORK:$DYLD_LIBRARY_PATH"
    export PYTHONHOME="$PY_FRAMEWORK"
elif [ -d "$RESOURCES_DIR/Python.framework" ]; then
    PY_FRAMEWORK="$RESOURCES_DIR/Python.framework/Versions/Current"
    export DYLD_LIBRARY_PATH="$PY_FRAMEWORK:$DYLD_LIBRARY_PATH"
    export PYTHONHOME="$PY_FRAMEWORK"
fi

export PYTHONPATH="$RESOURCES_DIR:$PYTHONPATH"
export PYTHONDONTWRITEBYTECODE=1
export TK_APP_NAME="Payroll Processor"

# Launch the GUI (capture output to a log so Finder launch errors are visible)
LOG_DIR="$HOME/Library/Logs/Payroll Processor"
LOG_FILE="$LOG_DIR/app.log"
mkdir -p "$LOG_DIR"

ARCH_BIN="/usr/bin/arch"
if [ -n "$PYTHON_ARCH" ] && [ -x "$ARCH_BIN" ]; then
    "$ARCH_BIN" -"$PYTHON_ARCH" "$PYTHON_BIN" payroll_gui.py >>"$LOG_FILE" 2>&1
else
    "$PYTHON_BIN" payroll_gui.py >>"$LOG_FILE" 2>&1
fi
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    /usr/bin/osascript <<EOF
display dialog "Payroll Processor closed unexpectedly. See log at:\n$LOG_FILE" buttons {"OK"} default button "OK"
EOF
fi
"""

    launcher_path = app_path / "Contents" / "MacOS" / "payroll_processor"
    with open(launcher_path, "w") as f:
        f.write(launcher_script)

    # Make launcher executable
    st = os.stat(launcher_path)
    os.chmod(launcher_path, st.st_mode | stat.S_IEXEC)

    # Prepare bundle for signing and sign embedded Python binaries explicitly
    _sanitize_bundle(app_path)
    _strip_resource_forks_with_ditto(app_path)
    _sanitize_bundle(app_path)
    _sign_embedded_code(app_path)

    # Sign app bundle (ad-hoc by default, or Developer ID if provided)
    sign_identity = os.environ.get("APPLE_CODESIGN_ID", "-")
    # No --deep: the embedded code is already signed inside-out above, and --deep
    # is both deprecated for signing and unreliable for nested bundles.
    sign_cmd = ["codesign", "--force", "--sign", sign_identity]
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
