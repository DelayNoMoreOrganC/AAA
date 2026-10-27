from pathlib import Path
import pytest
import workstation_entry as entry


def configured(monkeypatch, tmp_path):
    (tmp_path/'archive.db').touch()
    monkeypatch.setattr(entry, 'DATA', tmp_path)


def test_existing_service_is_opened_without_starting_or_stopping_processes(monkeypatch,tmp_path):
    configured(monkeypatch,tmp_path)
    monkeypatch.setattr(entry,'health',lambda:{'application':'gd-workstation','pid':123})
    monkeypatch.setattr(entry,'report',lambda value:False)
    monkeypatch.setattr(entry.subprocess,'run',lambda *a,**k:pytest.fail('existing server must not be replaced'))
    opened=[];monkeypatch.setattr(entry.webbrowser,'open',opened.append)
    assert entry.main([])==0
    assert opened==['http://127.0.0.1:8766/cases']


def test_unhealthy_occupied_port_never_spawns_a_second_server(monkeypatch,tmp_path):
    configured(monkeypatch,tmp_path)
    monkeypatch.setattr(entry,'health',lambda:None)
    monkeypatch.setattr(entry,'port_in_use',lambda:True)
    monkeypatch.setattr(entry.subprocess,'run',lambda *a,**k:pytest.fail('port occupied'))
    with pytest.raises(RuntimeError,match='未重复启动'):entry.main([])


def test_read_only_check_does_not_start_anything_when_offline(monkeypatch,tmp_path):
    configured(monkeypatch,tmp_path)
    monkeypatch.setattr(entry,'health',lambda:None)
    monkeypatch.setattr(entry.subprocess,'run',lambda *a,**k:pytest.fail('read-only'))
    monkeypatch.setattr(entry.webbrowser,'open',lambda *a:pytest.fail('read-only'))
    assert entry.main(['--check'])==1


def test_missing_existing_data_is_not_replaced_by_an_empty_database(monkeypatch,tmp_path):
    monkeypatch.setattr(entry,'DATA',tmp_path)
    with pytest.raises(RuntimeError,match='不会另建空数据库'):entry.main([])
    assert list(tmp_path.iterdir())==[]
