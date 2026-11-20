"""Bundle a relocatable macOS PostgreSQL runtime and its non-system dylibs."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

TOOLS = ('postgres', 'initdb', 'pg_ctl', 'pg_dump', 'pg_restore', 'psql', 'pg_config')


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def bundle_postgres(destination, pg_config=None):
    destination = Path(destination)
    pg_config = pg_config or os.environ.get('PAYROLL_PG_CONFIG') or shutil.which('pg_config')
    if not pg_config:
        raise RuntimeError('Building requires PostgreSQL 18: set PAYROLL_PG_CONFIG to its pg_config. End users do not need PostgreSQL installed.')
    paths = {key: Path(output(pg_config, '--' + key)) for key in ('bindir', 'sharedir', 'pkglibdir')}
    version = output(pg_config, '--version')
    if not version.split()[1].startswith('18.'):
        raise RuntimeError(f'The bundled database requires PostgreSQL 18; found {version}.')
    # Preserve the compiled relative layout, including Homebrew Cellar paths.
    # PostgreSQL relocates its share/lib paths relative to its executable.
    common = Path(os.path.commonpath([str(p) for p in paths.values()]))
    relative = {key: path.relative_to(common) for key, path in paths.items()}
    destination.mkdir(parents=True, exist_ok=True)
    binaries = destination / relative['bindir']
    binaries.mkdir(parents=True, exist_ok=True)
    originals = {}
    for name in TOOLS:
        source = paths['bindir'] / name
        target = binaries / name
        shutil.copy2(source, target)
        originals[source.resolve()] = target
    for key in ('sharedir', 'pkglibdir'):
        shutil.copytree(paths[key], destination / relative[key], symlinks=False, dirs_exist_ok=True)
        for source in paths[key].rglob('*'):
            if source.is_file():
                originals[source.resolve()] = destination / relative[key] / source.relative_to(paths[key])
    dependency_dir = destination / 'dependencies'
    dependency_dir.mkdir(exist_ok=True)
    queue = [(source, target) for source, target in originals.items()
             if target.suffix in ('.dylib', '.so') or target.parent == binaries]
    handled = set()
    packages = set()
    while queue:
        source, target = queue.pop()
        if target in handled:
            continue
        handled.add(target)
        listing = output('otool', '-L', target)
        for line in listing.splitlines()[1:]:
            dependency = line.strip().split(' (', 1)[0]
            if dependency.startswith(('/usr/lib/', '/System/')):
                continue
            if dependency.startswith('@loader_path/'):
                original = (source.parent / dependency.removeprefix('@loader_path/')).resolve()
            elif dependency.startswith('/'):
                original = Path(dependency).resolve()
            else:
                raise RuntimeError(f'Unresolved dependency {dependency} in {source}')
            if original == source:
                subprocess.check_call(['install_name_tool', '-id', '@loader_path/' + target.name, str(target)], stderr=subprocess.DEVNULL)
                continue
            if original not in originals:
                if not original.exists():
                    raise RuntimeError(f'Missing runtime dependency: {dependency}')
                dest = dependency_dir / original.name
                if dest.exists():
                    raise RuntimeError(f'Conflicting dependency name: {original.name}')
                shutil.copy2(original, dest)
                originals[original] = dest
                queue.append((original, dest))
            replacement = '@loader_path/' + os.path.relpath(originals[original], target.parent)
            subprocess.check_call(['install_name_tool', '-change', dependency, replacement, str(target)], stderr=subprocess.DEVNULL)
            if 'Cellar' in original.parts:
                index = original.parts.index('Cellar')
                packages.add(Path(*original.parts[:index + 3]))
        subprocess.check_call(['codesign', '--force', '--sign', '-', str(target)], stderr=subprocess.DEVNULL)
    notices = destination / 'licenses'
    notices.mkdir(exist_ok=True)
    packages.add(paths['bindir'].parent)
    for package in packages:
        for pattern in ('COPYRIGHT*', 'COPYING*', 'LICENSE*', 'LICENCE*', 'NOTICE*'):
            for source in package.glob(pattern):
                if source.is_file():
                    shutil.copy2(source, notices / f'{package.parent.name}-{package.name}-{source.name}')
    minimum_versions = []
    for binary in handled:
        minimum_versions.extend(re.findall(r'\bminos\s+([0-9.]+)', output('vtool', '-show-build', binary)))
    minimum = max(minimum_versions or ['10.12'], key=lambda value: tuple(map(int, value.split('.'))))
    manifest = {'version': version, 'major': '18', 'architecture': platform.machine(), 'min_macos': minimum,
                **{key: str(path) for key, path in relative.items()}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for key in ('sharedir', 'pkglibdir'):
        found = Path(output(binaries / 'pg_config', '--' + key)).resolve()
        if found != (destination / relative[key]).resolve():
            raise RuntimeError(f'PostgreSQL {key} did not relocate: {found}')
    return manifest


if __name__ == '__main__':
    import sys
    print(bundle_postgres(sys.argv[1]))
