"""Private app-managed PostgreSQL for first-run installations on macOS.

Uses a user-only Unix socket, peer authentication and no TCP listener. Existing
external connection settings are never replaced by automatic setup.
"""
from __future__ import annotations

import atexit
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
from contextlib import contextmanager

from app_paths import CONFIG_DIR, CONFIG_PATH

_MUTEX = threading.RLock()
_READY = None
_LEASE = None
_RUNTIME = None


def runtime_path():
    override = os.environ.get('PAYROLL_POSTGRES_RUNTIME')
    path = Path(override).expanduser() if override else Path(__file__).resolve().parent / 'postgres'
    return path if (path / 'manifest.json').is_file() else None


def manifest(runtime):
    info = json.loads((runtime / 'manifest.json').read_text())
    for key in ('bindir', 'sharedir', 'pkglibdir'):
        candidate = (runtime / info[key]).resolve()
        if not candidate.is_relative_to(runtime.resolve()):
            raise RuntimeError('Invalid bundled database runtime path.')
    return info


def tool_path(name):
    runtime = runtime_path()
    if runtime is None:
        return None
    tool = runtime / manifest(runtime)['bindir'] / name
    return str(tool) if tool.is_file() else None


def needs_setup(config, config_path=None):
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    return bool(runtime_path()) and ((config.get('mode') == 'bundled' and config.get('enabled')) or not path.exists())


def _private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError(f'Database directory is not a private folder owned by this user: {path}')
    path.chmod(0o700)
    return path


def _paths():
    root = _private_directory(CONFIG_DIR / 'local-postgres')
    # macOS limits Unix socket path length; a per-user, per-data-root name stays short.
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    sockets = _private_directory(Path('/tmp') / f'payroll-pg-{os.getuid()}-{key}')
    return root, sockets


@contextmanager
def _cluster_lock(root):
    with (root / 'setup.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _env():
    return {key: value for key, value in os.environ.items()
            if not key.startswith(('PG', 'DYLD_'))}


def _run(runtime, info, name, *args, timeout=60, check=True):
    result = subprocess.run([str(runtime / info['bindir'] / name), *map(str, args)],
                            env=_env(), capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Local database {name} failed: {(result.stderr or result.stdout).strip()[-2500:]}')
    return result


def _connect(config, database=None):
    import psycopg2
    return psycopg2.connect(host=config['host'], port=config['port'], user=config['user'],
                            dbname=database or config['database'], sslmode='disable', connect_timeout=5)


def ensure_started():
    """Initialize/start once per process and return canonical connection settings."""
    global _READY, _LEASE, _RUNTIME
    with _MUTEX:
        if _READY is not None:
            return _READY.copy()
        runtime = runtime_path()
        if runtime is None:
            raise RuntimeError('The bundled database runtime is missing. Reinstall Payroll Processor.')
        info = manifest(runtime)
        root, sockets = _paths()
        data = root / 'data'
        user = pwd.getpwuid(os.getuid()).pw_name
        config = dict(mode='bundled', enabled=True, host=str(sockets), port=55432,
                      database='payroll', user=user, password='', sslmode='disable', role='editor', audit_user=user)
        with _cluster_lock(root):
            if data.is_symlink():
                raise RuntimeError('The managed database folder cannot be a symbolic link. Existing data was left untouched.')
            if data.exists():
                marker = data / 'PG_VERSION'
                if not marker.is_file():
                    raise RuntimeError('The local database folder is incomplete. It has been left untouched; restore a backup or contact support.')
                if marker.read_text().strip() != str(info['major']):
                    raise RuntimeError('This database requires a different PostgreSQL major version. An explicit database upgrade is required; existing data was left untouched.')
            else:
                staging = Path(tempfile.mkdtemp(prefix='initializing-', dir=root))
                try:
                    _run(runtime, info, 'initdb', '-D', staging, '-L', runtime / info['sharedir'],
                         '-U', user, '--auth-local=peer', '--auth-host=reject', '--encoding=UTF8', '--locale=C', timeout=120)
                    staging.rename(data)
                except Exception:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise
            status = _run(runtime, info, 'pg_ctl', '-D', data, 'status', check=False)
            if status.returncode:
                options = ['-h', '', '-k', str(sockets), '-p', str(config['port']),
                           '-c', 'unix_socket_permissions=0700', '-c', 'max_connections=30',
                           '-c', 'shared_buffers=32MB', '-c', 'timezone=UTC']
                _run(runtime, info, 'pg_ctl', '-D', data, '-l', root / 'server.log',
                     '-o', shlex.join(options), '-w', '-t', '30', 'start', timeout=40)
            # Acquire a per-process lease before releasing the cluster lock. Another
            # open app/CLI instance keeps the server alive when this process exits.
            clients = _private_directory(root / 'clients')
            lease = (clients / str(os.getpid())).open('a+')
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _LEASE = lease
            _RUNTIME = runtime
            try:
                from psycopg2 import sql
                conn = _connect(config, 'postgres')
                conn.autocommit = True
                try:
                    with conn.cursor() as cur:
                        cur.execute('SELECT 1 FROM pg_database WHERE datname=%s', (config['database'],))
                        if cur.fetchone() is None:
                            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(config['database'])))
                finally:
                    conn.close()
                schema = Path(__file__).resolve().parent / 'create_database.sql'
                if not schema.exists():
                    schema = Path(__file__).resolve().parents[3] / 'create_database.sql'
                with _connect(config) as conn:
                    with conn.cursor() as cur:
                        cur.execute(schema.read_text())
            except Exception:
                _LEASE.close()
                _LEASE = None
                _stop_if_unused(root, runtime)
                raise
            _READY = config
        return config.copy()


def _stop_if_unused(root, runtime):
    for path in (root / 'clients').iterdir():
        with path.open('a+') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
    try:
        _run(runtime, manifest(runtime), 'pg_ctl', '-D', root / 'data',
             '-m', 'fast', '-w', '-t', '20', 'stop', timeout=25, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def stop():
    """Stop only the private cluster, and only after its last app client exits."""
    global _READY, _LEASE, _RUNTIME
    with _MUTEX:
        if _LEASE is None:
            return
        root, _sockets = _paths()
        with _cluster_lock(root):
            _LEASE.close()
            _LEASE = None
            if _RUNTIME:
                _stop_if_unused(root, _RUNTIME)
            _READY = None


atexit.register(stop)
