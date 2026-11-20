import json
from pathlib import Path
import stat

import pytest

import db_storage as db
import local_database as local


@pytest.mark.parametrize('exists,config,expected', [
    (False, {}, True),
    (True, {'enabled': True, 'host': 'localhost'}, False),
    (True, {'enabled': False}, False),
    (True, {'enabled': True, 'mode': 'bundled'}, True),
    (True, {'enabled': False, 'mode': 'bundled'}, False),
])
def test_automatic_setup_preserves_existing_connections(tmp_path, monkeypatch, exists, config, expected):
    monkeypatch.setattr(local, 'runtime_path', lambda: tmp_path)
    settings = tmp_path / 'settings.json'
    if exists:
        settings.write_text(json.dumps(config))
    assert local.needs_setup(config, settings) is expected


def test_development_without_runtime_does_not_auto_enable_database(tmp_path, monkeypatch):
    monkeypatch.setattr(local, 'runtime_path', lambda: None)
    assert local.needs_setup({}, tmp_path / 'missing.json') is False


def test_private_directory_refuses_links_and_sets_owner_only_permissions(tmp_path):
    folder = local._private_directory(tmp_path / 'private')
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    link = tmp_path / 'link'
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(RuntimeError, match='private folder'):
        local._private_directory(link)


def test_manifest_cannot_escape_bundle(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(bindir='../outside', sharedir='share', pkglibdir='lib')))
    with pytest.raises(RuntimeError, match='runtime path'):
        local.manifest(tmp_path)


def test_major_version_mismatch_never_starts_or_reinitializes_database(tmp_path, monkeypatch):
    data = tmp_path / 'cluster' / 'data'
    data.mkdir(parents=True)
    (data / 'PG_VERSION').write_text('17\n')
    monkeypatch.setattr(local, '_READY', None)
    monkeypatch.setattr(local, 'runtime_path', lambda: tmp_path)
    monkeypatch.setattr(local, 'manifest', lambda _path: {'major': '18'})
    monkeypatch.setattr(local, '_paths', lambda: (data.parent, tmp_path / 'socket'))
    monkeypatch.setattr(local, '_run', lambda *args, **kwargs: pytest.fail('Must not start or initialize'))
    with pytest.raises(RuntimeError, match='different PostgreSQL major'):
        local.ensure_started()
    assert (data / 'PG_VERSION').read_text() == '17\n'


def test_database_config_write_is_atomic_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(db, 'CONFIG_PATH', tmp_path / 'config.json')
    config = {'host': 'existing', 'enabled': True}
    db.save_db_config(config)
    assert json.loads(db.CONFIG_PATH.read_text()) == config
    assert stat.S_IMODE(db.CONFIG_PATH.stat().st_mode) == 0o600
    assert list(tmp_path.glob('.db-config-*')) == []


def test_postgres_environment_cannot_inherit_foreign_connection_or_loader_settings(monkeypatch):
    monkeypatch.setenv('PGOPTIONS', 'foreign')
    monkeypatch.setenv('PGHOST', 'remote')
    monkeypatch.setenv('DYLD_LIBRARY_PATH', '/foreign')
    env = local._env()
    assert not any(key.startswith(('PG', 'DYLD_')) for key in env)


@pytest.fixture
def bundled_cluster(tmp_path, monkeypatch):
    import os
    runtime = os.environ.get('PAYROLL_BUNDLED_PG_QA')
    if not runtime:
        pytest.skip('Set PAYROLL_BUNDLED_PG_QA to a built PostgreSQL runtime for isolated lifecycle tests.')
    monkeypatch.setenv('PAYROLL_POSTGRES_RUNTIME', runtime)
    monkeypatch.setattr(local, 'CONFIG_DIR', tmp_path / 'config')
    monkeypatch.setattr(local, '_READY', None)
    monkeypatch.setattr(local, '_LEASE', None)
    yield tmp_path
    local.stop()


def test_bundled_first_run_backup_restore_and_restart(bundled_cluster, monkeypatch):
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    config = local.ensure_started()
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO employees(employee_code,full_name) VALUES('LOCAL','Δοκιμή Εργαζομένου')")
            cur.execute('SHOW listen_addresses')
            assert cur.fetchone() == ('',)
            cur.execute('SELECT inet_server_addr()')
            assert cur.fetchone() == (None,)
    backup = bundled_cluster / 'backup.dump'
    db.backup_database(config, str(backup))
    with db.get_connection(config) as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM employees')
    db.restore_database(config, str(backup))
    local.stop()
    restarted = local.ensure_started()
    assert restarted == config
    with db.get_connection(restarted) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT full_name FROM employees')
            assert cur.fetchone() == ('Δοκιμή Εργαζομένου',)
    local.stop()
    runtime = local.runtime_path()
    status = local._run(runtime, local.manifest(runtime), 'pg_ctl', '-D', local.CONFIG_DIR / 'local-postgres/data', 'status', check=False)
    assert status.returncode != 0


def test_bundled_server_stays_up_until_last_app_exits(bundled_cluster):
    import os
    import select
    import subprocess
    import sys
    local.ensure_started()
    env = os.environ.copy()
    env['PAYROLL_PROCESSOR_DATA_ROOT'] = str(bundled_cluster)
    env['PYTHONPATH'] = str(Path(local.__file__).parent)
    child = subprocess.Popen([sys.executable, '-c', '''
import sys
import local_database as local
config = local.ensure_started()
print('ready', flush=True)
sys.stdin.readline()
with local._connect(config) as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT 1')
        assert cur.fetchone() == (1,)
print('still connected', flush=True)
local.stop()
'''], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        ready, _, _ = select.select([child.stdout], [], [], 45)
        assert ready
        assert child.stdout.readline().strip() == 'ready'
        local.stop()
        output, error = child.communicate('\n', timeout=35)
        assert child.returncode == 0, error
        assert 'still connected' in output
        runtime = local.runtime_path()
        assert local._run(runtime, local.manifest(runtime), 'pg_ctl', '-D', local.CONFIG_DIR / 'local-postgres/data', 'status', check=False).returncode != 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
            local.ensure_started()
            local.stop()


def test_gui_first_run_clears_setup_notice_and_refreshes_views(monkeypatch):
    from unittest.mock import Mock
    from payroll_gui import PayrollProcessorGUI
    gui = PayrollProcessorGUI.__new__(PayrollProcessorGUI)
    gui._local_db_pending = True
    gui._local_db_saved_config = {}
    gui.db_config = {'enabled': False}
    gui.show_toast = Mock()
    gui._refresh_setup_banner = Mock()
    gui._initialize_database_schema_async = Mock()
    gui._refresh_all_views = Mock()
    gui._run_async = lambda name, work, done, failed: done(work())
    config = dict(mode='bundled', enabled=True, role='editor', audit_user='test')
    monkeypatch.setattr(local, 'ensure_started', lambda: config.copy())
    save = Mock()
    monkeypatch.setattr(db, 'save_db_config', save)
    gui._prepare_database()
    assert gui.db_config == config
    assert gui._local_db_pending is False
    assert gui._refresh_setup_banner.call_count == 2
    gui._refresh_all_views.assert_called_once()
    save.assert_called_once_with(config)
