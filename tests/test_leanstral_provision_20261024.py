"""Offline guards; no model download, inference, CUDA allocation or service."""
import importlib.util
from pathlib import Path

import pytest

PATH=Path(__file__).parents[1]/'tools/provision_leanstral_20261024.py'
spec=importlib.util.spec_from_file_location('leanstral_provision_guard',PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def resources():
    return {'mem_available_bytes':64*m.GIB,'storage_available_bytes':64*m.GIB,
            'gpus':[{'used_mib':300,'free_mib':23*1024,'utilization_percent':0} for _ in range(2)]}


def test_separate_card_limits_do_not_pool_vram():
    r=resources();m.check_resources(r,loading=True)
    r['gpus'][0]['used_mib']=20*1024+1
    with pytest.raises(RuntimeError,match='Per-card'):m.check_resources(r)


@pytest.mark.parametrize('field,value', [('mem_available_bytes',16*m.GIB-1),('storage_available_bytes',16*m.GIB-1)])
def test_host_and_disk_reserves_are_real_independent_limits(field,value):
    r=resources();r[field]=value
    with pytest.raises(RuntimeError):m.check_resources(r)


def test_initial_loading_reserves_more_than_running():
    r=resources();r['mem_available_bytes']=40*m.GIB;m.check_resources(r)
    with pytest.raises(RuntimeError):m.check_resources(r,loading=True)


def test_existing_busy_gpu_is_not_displaced():
    r=resources();r['gpus'][1]['utilization_percent']=99
    with pytest.raises(RuntimeError,match='compete'):m.check_resources(r,loading=True)


def test_own_rss_ceiling_ignores_large_virtual_address_reservations():
    m.check_resources(resources(),rss=47*m.GIB)
    with pytest.raises(RuntimeError,match='RSS'):m.check_resources(resources(),rss=48*m.GIB+1)


def test_partial_model_is_not_marked_verified(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    (tmp_path/(m.MODEL_NAME+'.partial')).write_bytes(b'GGUF-incomplete')
    with pytest.raises(RuntimeError,match='incomplete'):m.verify()
    assert not (tmp_path/'weights-verified.json').exists()


def test_malformed_header_never_drives_offload_plan(tmp_path):
    p=tmp_path/'wrong.gguf';p.write_bytes(b'NOT-A-GGUF-MODEL')
    with pytest.raises(RuntimeError):m.model_header(p)


def test_foreign_model_symlink_is_not_modified_or_adopted(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    other=tmp_path/'different-model';other.write_bytes(b'untouched')
    (tmp_path/(m.MODEL_NAME+'.partial')).symlink_to(other)
    before=other.stat().st_mode
    with pytest.raises(RuntimeError,match='ordinary'):m.verify()
    assert other.read_bytes()==b'untouched' and other.stat().st_mode==before
