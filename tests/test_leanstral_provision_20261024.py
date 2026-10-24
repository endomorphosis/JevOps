"""Offline guards; no model download, inference, CUDA allocation or service."""
import importlib.util
import hashlib
import json
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


def test_arc_preload_estimate_is_explicit_and_not_guaranteed_memory():
    r=resources();r['mem_available_bytes']=28*m.GIB
    r['zfs_arc']={'size':90*m.GIB,'c_min':4*m.GIB,'data_size':76*m.GIB,'mru_evictable_data':48*m.GIB,'mfu_evictable_data':24*m.GIB}
    assessment=m.check_resources(r,loading=True,cpu_weight_bytes=34*m.GIB)
    assert assessment['raw_mem_available_bytes']==28*m.GIB
    assert assessment['arc_credit_bytes']==34*m.GIB and assessment['arc_reclaim_guaranteed'] is False


@pytest.mark.parametrize('arc',[None,{}, {'size':100}, {'size':90,'c_min':4,'data_size':76,'mru_evictable_data':-1,'mfu_evictable_data':24}])
def test_missing_or_invalid_arc_cannot_authorize_capacity(arc):
    r=resources();r.update(mem_available_bytes=28*m.GIB,zfs_arc=arc)
    with pytest.raises(RuntimeError,match='ARC'):m.check_resources(r,loading=True,cpu_weight_bytes=34*m.GIB)


def test_arc_never_weakens_actual_loading_or_running_reserve():
    r=resources();r['mem_available_bytes']=15*m.GIB
    r['zfs_arc']={'size':90*m.GIB,'c_min':4*m.GIB,'data_size':76*m.GIB,'mru_evictable_data':48*m.GIB,'mfu_evictable_data':24*m.GIB}
    for loading in (True,False):
        with pytest.raises(RuntimeError,match='reserve'):m.check_resources(r,loading=loading,cpu_weight_bytes=34*m.GIB)


def old_arc_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    original=tmp_path/'arc-aware-preload-attempt.json'
    original.write_text('{"authorized_attempt":1,"actual_prior_attempt":"private fixture"}\n')
    monkeypatch.setattr(m,'PRIOR_ARC_ATTEMPT_SHA',hashlib.sha256(original.read_bytes()).hexdigest())
    return original


def test_explicit_fixed_phase_preserves_old_marker_and_reserves_once(tmp_path,monkeypatch):
    original=old_arc_fixture(tmp_path,monkeypatch)
    before=m.identity(original);raw=original.read_bytes()
    marker,phase,prior=m.arc_preload_target()
    assert phase=='gpu-release-20261024' and marker.name=='arc-aware-preload-attempt-gpu-release-20261024.json'
    result=m.reserve_arc_preload({'arc_credit_bytes':34*m.GIB},{'fixture_resources':True},{'header_magic':'GGUF'})
    value=json.loads(result.read_text())
    assert value['preload_phase']==phase and value['authorized_attempt']==1
    assert value['prior_attempt_sha256']==prior and value['authorization_kind']=='fixed-reviewed-phase'
    assert value['provisioner_source_sha256']==m.digest(Path(m.__file__))
    assert result.stat().st_mode&0o777==0o600
    assert m.identity(original)==before and original.read_bytes()==raw
    new_bytes=result.read_bytes()
    with pytest.raises(FileExistsError):m.reserve_arc_preload({}, {}, {})
    assert result.read_bytes()==new_bytes and original.read_bytes()==raw


def test_consumed_phase_survives_reload_and_cannot_be_renamed_by_environment(tmp_path,monkeypatch):
    original=old_arc_fixture(tmp_path,monkeypatch)
    marker=m.reserve_arc_preload({}, {}, {})
    monkeypatch.setenv('JEVOPS_LEANSTRAL_PRELOAD_PHASE','invented-new-attempt')
    spec2=importlib.util.spec_from_file_location('fresh_provisioner_phase_guard',PATH)
    fresh=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(fresh)
    fresh.ROOT=tmp_path;fresh.PRIOR_ARC_ATTEMPT_SHA=hashlib.sha256(original.read_bytes()).hexdigest()
    assert fresh.arc_preload_target()[0]==marker
    with pytest.raises(FileExistsError):fresh.reserve_arc_preload({}, {}, {})
    assert not (tmp_path/'arc-aware-preload-attempt-invented-new-attempt.json').exists()


def test_unreviewed_or_symlinked_old_attempt_never_authorizes_new_phase(tmp_path,monkeypatch):
    original=old_arc_fixture(tmp_path,monkeypatch)
    original.write_text('{"changed":"unreviewed attempt"}\n')
    with pytest.raises(RuntimeError,match='custody'):m.arc_preload_target()
    original.unlink();other=tmp_path/'foreign';other.write_text('unchanged foreign bytes')
    original.symlink_to(other)
    with pytest.raises(RuntimeError,match='ordinary'):m.arc_preload_target()
    assert not (tmp_path/'arc-aware-preload-attempt-gpu-release-20261024.json').exists()
    assert other.read_text()=='unchanged foreign bytes'


def test_fresh_store_retains_single_original_initial_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'ROOT',tmp_path)
    marker,phase,prior=m.arc_preload_target()
    assert marker.name=='arc-aware-preload-attempt.json' and phase=='initial-preload' and prior is None
    m.reserve_arc_preload({}, {}, {})
    with pytest.raises(RuntimeError,match='custody'):m.arc_preload_target()
