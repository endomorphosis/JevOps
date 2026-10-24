#!/usr/bin/env python3
"""Owned, bounded local inference provisioning. Never training or proof authority.

Public downloads live on the explicitly selected storage volume. The server
binds loopback only, retains independent GPU locks, and may stop only its own
exact child/process group when a resource guard fails.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/storage/hf_cache/jevops-leanstral-20261024')
MODEL_NAME = 'Leanstral-1.5-119B-A6B-Q4_K_M.gguf'
MODEL_SHA = '8d7bdbfa733c3fcde4c9ce527ba3d4aa3a49af77e7767b3ed5ae649e6c92b902'
MODEL_BYTES = 72159246080
REVISION = '929d4958b79a5625d189addd7c25be362748aed4'
MODEL_URL = f'https://huggingface.co/GZGavinZhao/Leanstral-1.5-119B-A6B-GGUF/resolve/{REVISION}/{MODEL_NAME}'
RUNTIME = ROOT/'runtime-b11850/llama-b11850'
CUDA_LIB = ROOT/'runtime-b11850/cudart-llama-b11850-bin-ubuntu-cuda-12.8-x64'
PORT = 18180
GIB = 1024**3
FALSE = {'training_executed': False, 'proof_verified': False, 'proof_authority': False,
         'weights_officially_attested': False, 'conversion_quality_measured': False}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def save(name, value):
    path=ROOT/name;temporary=path.with_name('.'+path.name+'.'+str(os.getpid()))
    raw=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
    with temporary.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.chmod(temporary,0o600);os.replace(temporary,path)


def identity(path):
    s=path.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_nlink==1,'Owned single-link ordinary file required')
    return {'device':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}


def model_header(path):
    """Parse bounded real GGUF metadata and tensor offsets, never tensor values."""
    formats={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
    with path.open('rb') as f:
        def read(n):
            require(0<=n<=100_000_000 and f.tell()+n<=64*1024*1024,'Bounded GGUF header required')
            raw=f.read(n);require(len(raw)==n,'Incomplete GGUF header');return raw
        def integer(fmt):return struct.unpack('<'+fmt,read(struct.calcsize(fmt)))[0]
        def string():return read(integer('Q')).decode('utf-8')
        def value(kind,keep=False):
            if kind in formats:return integer(formats[kind])
            if kind==8:return string()
            if kind==9:
                element,count=integer('I'),integer('Q');require(count<=2_000_000,'GGUF array budget')
                for _ in range(count):value(element)
                return {'element_type':element,'count':count}
            raise RuntimeError('Unsupported GGUF metadata type')
        require(read(4)==b'GGUF' and integer('I')==3,'Expected GGUFv3')
        tensors,metadata=integer('Q'),integer('Q');require(tensors<=10000 and metadata<=1000,'GGUF header count budget')
        selected={}
        for _ in range(metadata):
            key=string();item=value(integer('I'))
            if key in {'general.architecture','general.name','general.file_type','general.license','mistral4.block_count','mistral4.embedding_length','mistral4.context_length'}:selected[key]=item
            if key=='tokenizer.chat_template':selected[key]={'bytes':len(item.encode()),'sha256':hashlib.sha256(item.encode()).hexdigest()}
        table=[]
        for _ in range(tensors):
            name=string();nd=integer('I');require(nd<=4,'GGUF tensor geometry budget')
            shape=[integer('Q') for _ in range(nd)];quant,offset=integer('I'),integer('Q');table.append((offset,name,quant,shape))
        start=(f.tell()+31)//32*32;table.sort();groups={}
        for index,(offset,name,_,_) in enumerate(table):
            end=table[index+1][0] if index+1<len(table) else MODEL_BYTES-start
            require(end>=offset,'GGUF offsets out of order')
            key='.'.join(name.split('.')[:2]) if name.startswith('blk.') else 'non_layers'
            groups[key]=groups.get(key,0)+end-offset
    require(selected.get('general.architecture')=='mistral4' and selected.get('general.file_type')==15
            and selected.get('mistral4.block_count')==36 and selected.get('tokenizer.chat_template',{}).get('bytes',0)>0,
            'Pinned mistral4 Q4_K_M architecture/template required')
    offload=sum(groups[f'blk.{i}'] for i in range(18,36))
    return {'metadata':selected,'tensor_count':tensors,'tensor_bytes_by_group':groups,
            'selected_gpu_layers':18,'estimated_gpu_tensor_bytes_total':offload,
            'estimated_cpu_tensor_bytes':MODEL_BYTES-offload,
            'estimates_exclude_KV_compute_driver_buffers':True}


def download():
    partial=ROOT/(MODEL_NAME+'.partial');target=ROOT/MODEL_NAME
    if target.exists():return verify()
    require(os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize>MODEL_BYTES-(partial.stat().st_size if partial.exists() else 0)+32*GIB,
            'Insufficient storage headroom')
    subprocess.run(['curl','--location','--fail','--retry','5','--retry-connrefused','--connect-timeout','20','--max-time','7200',
                    '--continue-at','-','--silent','--show-error','--output',str(partial),MODEL_URL],check=True)
    return verify()


def verify():
    target=ROOT/MODEL_NAME;path=target if target.exists() else ROOT/(MODEL_NAME+'.partial')
    before=identity(path);require(before['bytes']==MODEL_BYTES,'Model download incomplete')
    observed=digest(path);require(observed==MODEL_SHA and identity(path)==before,'Complete model SHA/custody mismatch')
    header=model_header(path)
    require(identity(path)==before,'Model changed during metadata inspection')
    if path!=target:
        with path.open('rb') as stream:os.fsync(stream.fileno())
        os.link(path,target);path.unlink()  # Refuse an unexpected existing target.
    os.chmod(target,0o444)
    result={'schema':'jevops.leanstral-verified-weights.v1','model_path':str(target),'sha256':observed,'bytes':MODEL_BYTES,
            'repository_revision':REVISION,'declared_license':'apache-2.0','identity':identity(target),
            'verified_at':time.time(),'actual_header':header,**FALSE}
    save('weights-verified.json',result);print(json.dumps({'weights_verified':True,'sha256':observed,'bytes':MODEL_BYTES,**FALSE}),flush=True)
    return result


def resources():
    mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1);mem[key]=int(value.split()[0])*1024
    rows=subprocess.run(['nvidia-smi','--query-gpu=index,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],
                        check=True,capture_output=True,text=True,timeout=10).stdout.splitlines()
    devices=[dict(zip(('index','used_mib','free_mib','utilization_percent'),[int(x.strip()) for x in row.split(',')])) for row in rows]
    arc=None;stats=Path('/proc/spl/kstat/zfs/arcstats')
    if stats.exists():
        fields={}
        try:
            for line in stats.read_text().splitlines()[2:]:
                parts=line.split()
                if len(parts)==3 and parts[0] in {'size','c_min','data_size','mru_evictable_data','mfu_evictable_data'}:
                    fields[parts[0]]=int(parts[2])
            arc=fields
        except (OSError,ValueError):arc=None
    return {'mem_available_bytes':mem['MemAvailable'],'swap_free_bytes':mem.get('SwapFree'),'zfs_arc':arc,
            'storage_available_bytes':os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize,'gpus':devices}


def request(path, *, payload=None, timeout=5):
    endpoint=f'http://127.0.0.1:{PORT}'+path
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(endpoint,data=data,headers={'Content-Type':'application/json','Accept':'application/json'})
    with op.open(req,timeout=timeout) as response:
        raw=response.read(2_097_153);require(len(raw)<=2_097_152,'Response byte bound')
        return response.status,json.loads(raw)


def process_rss(pid):
    for line in (Path('/proc')/str(pid)/'status').read_text().splitlines():
        if line.startswith('VmRSS:'):return int(line.split()[1])*1024
    return 0


def check_resources(observation, *, rss=0, loading=False, cpu_weight_bytes=None):
    require(type(rss) is int and 0<=rss<=48*GIB,'Owned server RSS ceiling reached')
    raw=observation['mem_available_bytes'];require(raw>=16*GIB,'Host available-memory reserve reached')
    estimate=raw;credit=0
    if loading and raw<48*GIB:
        arc=observation.get('zfs_arc');keys={'size','c_min','data_size','mru_evictable_data','mfu_evictable_data'}
        require(type(arc) is dict and set(arc)==keys and all(type(v) is int and v>=0 for v in arc.values())
                and 0<arc['c_min']<arc['size'] and arc['data_size']<=arc['size']
                and arc['mru_evictable_data']+arc['mfu_evictable_data']<=arc['data_size'],
                'ARC-dependent preload requires valid actual evictable-cache diagnostics')
        require(type(cpu_weight_bytes) is int and 0<cpu_weight_bytes<=MODEL_BYTES,'Actual CPU tensor budget required')
        credit=min(arc['size']-arc['c_min'],arc['mru_evictable_data']+arc['mfu_evictable_data'],cpu_weight_bytes)
        estimate+=credit
    if loading:require(estimate>=48*GIB,'Conservative preload-capacity estimate insufficient')
    require(observation['storage_available_bytes']>=16*GIB,'Storage headroom guard')
    require(len(observation['gpus'])==2 and all(g['used_mib']<=20*1024 for g in observation['gpus']), 'Per-card GPU ceiling reached')
    if loading:
        require(all(g['free_mib']>=22*1024 and g['utilization_percent']<=10 for g in observation['gpus']), 'Do not compete with existing GPU work')
    return {'raw_mem_available_bytes':raw,'arc_credit_bytes':credit,'preload_capacity_estimate_bytes':estimate,
            'arc_reclaim_guaranteed':False,'actual_runtime_reserve_bytes':16*GIB}


def direct_io_probe(model):
    descriptor=os.open(model,os.O_RDONLY|os.O_DIRECT)
    try:
        with mmap.mmap(-1,4096) as buffer:
            count=os.preadv(descriptor,[buffer],0)
            require(count==4096 and buffer[:4]==b'GGUF','DirectIO model-header probe failed')
    finally:os.close(descriptor)
    return {'requested_direct_io':True,'actual_O_DIRECT_read_bytes':4096,'header_magic':'GGUF'}


def serve():
    verified=json.loads((ROOT/'weights-verified.json').read_text());model=ROOT/MODEL_NAME
    require(verified['sha256']==MODEL_SHA and identity(model)==verified['identity'],'Verify full model once before serving; changed files refuse')
    runtime=json.loads((ROOT/'runtime-verified.json').read_text());binary=RUNTIME/'llama-server'
    require(runtime['source_commit']=='9ae73e68f5a78933c0d988bbd17bf4647ad6a0b2'
            and digest(binary)==runtime['server_sha256'],'Pinned runtime binary changed')
    for name,expected in runtime['files'].items():
        file=ROOT/name;require(file.resolve().is_relative_to(ROOT) and digest(file)==expected,'Runtime library custody changed')
    held=[];process=None;running=True;ready=False;peak_rss=0;peak_gpu={};start=time.monotonic()
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        for name in ('operator','gpu0','gpu1'):
            handle=(ROOT/(name+'.lock')).open('a+');fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);held.append(handle)
        r=resources();assessment=check_resources(r,loading=True,cpu_weight_bytes=verified['actual_header']['estimated_cpu_tensor_bytes'])
        dio=direct_io_probe(model)
        if assessment['arc_credit_bytes']:
            marker=ROOT/'arc-aware-preload-attempt.json'
            # Exactly one explicitly authorized ARC-dependent attempt. Failure
            # is retained; there is no automatic load/restart loop.
            with marker.open('x') as stream:
                json.dump({'authorized_attempt':1,'actor_pid':os.getpid(),'observed_at':time.time(),
                           'capacity_assessment':assessment,'raw_resources':r,'direct_io':dio,**FALSE},stream,indent=2)
                stream.flush();os.fsync(stream.fileno())
        with socket.socket() as probe:probe.bind(('127.0.0.1',PORT))
        env={k:v for k,v in os.environ.items() if not k.startswith('LLAMA_ARG_') and k!='LD_PRELOAD'}
        env['LD_LIBRARY_PATH']=str(CUDA_LIB)+':'+str(RUNTIME)
        env['CUDA_VISIBLE_DEVICES']='0,1';env['OMP_NUM_THREADS']='8'
        command=[str(binary),'--model',str(model),'--alias','Leanstral','--host','127.0.0.1','--port',str(PORT),
                 '--ctx-size','2048','--parallel','1','--threads','8','--threads-batch','8','--batch-size','64','--ubatch-size','32',
                 '--n-gpu-layers','18','--split-mode','layer','--tensor-split','1,1','--fit','off','--load-mode','dio',
                 '--flash-attn','off','--jinja','--reasoning','off','--no-warmup']
        save('launch-intent.json',{'schema':'jevops.leanstral-launch-intent.v1','command':command,'baseline_resources':r,
                                  'preload_capacity_assessment':assessment,'actual_direct_io_probe':dio,
                                  'model_sha256':MODEL_SHA,'runtime_sha256':runtime['server_sha256'],'partial_gpu_offload':True,
                                  'rss_limit_bytes':48*GIB,'gpu_used_limit_mib_each':20*1024,'minimum_host_available_bytes':16*GIB,
                                  'owner_pid':os.getpid(),'preexisting_jobs_interrupted':False,**FALSE})
        with (ROOT/'server.log').open('ab',buffering=0) as log:
            process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            stat_text=(Path('/proc')/str(process.pid)/'stat').read_text();ticks=stat_text[stat_text.rfind(')')+2:].split()[19]
            save('server-owner.json',{'supervisor_pid':os.getpid(),'server_pid':process.pid,'server_start_ticks':ticks,
                                       'uid':os.getuid(),'command':command,'endpoint':f'http://127.0.0.1:{PORT}/v1',**FALSE})
            while running and process.poll() is None and time.monotonic()-start<86400:
                r=resources();rss=process_rss(process.pid);peak_rss=max(peak_rss,rss)
                for g in r['gpus']:peak_gpu[str(g['index'])]=max(peak_gpu.get(str(g['index']),0),g['used_mib'])
                check_resources(r,rss=rss)
                if not ready:
                    require(time.monotonic()-start<1200,'Loading readiness deadline exceeded')
                    try:
                        code,health=request('/health',timeout=2)
                        if code==200 and health.get('status')=='ok':
                            _,models=request('/v1/models');_,props=request('/props')
                            ready=True
                            save('server-ready.json',{'schema':'jevops.leanstral-server-ready.v1','ready':True,'endpoint':f'http://127.0.0.1:{PORT}/v1',
                                'actual_models':models,'actual_health':health,'model_sha256':MODEL_SHA,'runtime_sha256':runtime['server_sha256'],
                                'server_alias_is_not_weight_attestation':True,'declared_context':props.get('default_generation_settings',{}).get('n_ctx'),
                                'reported_model_basename':Path(str(props.get('model_path',''))).name,'ready_at':time.time(),**FALSE})
                    except (OSError,ValueError):pass
                save('server-resource-status.json',{'running':True,'ready':ready,'server_pid':process.pid,'observed_at':time.time(),
                    'rss_bytes':rss,'peak_rss_bytes':peak_rss,'peak_gpu_used_mib':peak_gpu,'resources':r,**FALSE})
                time.sleep(3)
        require(ready,'Server exited before readiness')
    finally:
        if process is not None and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        save('server-stopped.json',{'stopped_at':time.time(),'server_pid':process.pid if process else None,
            'exit_code':process.returncode if process else None,'peak_rss_bytes':peak_rss,'peak_gpu_used_mib':peak_gpu,**FALSE})
        save('server-resource-status.json',{'running':False,'ready':False,'observed_at':time.time(),
            'server_pid':process.pid if process else None,'peak_rss_bytes':peak_rss,'peak_gpu_used_mib':peak_gpu,**FALSE})
        for handle in held:handle.close()


def smoke():
    status=json.loads((ROOT/'server-resource-status.json').read_text());require(status.get('running') and status.get('ready') and time.time()-status['observed_at']<30,'Fresh live ready resource guard required')
    started=time.monotonic()
    code,result=request('/v1/chat/completions',payload={'model':'Leanstral','messages':[{'role':'user','content':'Reply only with the Lean tactic that proves: theorem local_identity (x : Nat) : x = x := by'}],
        'max_tokens':16,'temperature':0,'stream':False},timeout=180)
    require(code==200 and result.get('model')=='Leanstral' and isinstance(result.get('choices'),list) and result['choices'],'Actual bounded inference response required')
    save('inference-smoke.json',{'schema':'jevops.leanstral-inference-smoke.v1','actual_response':result,'wall_seconds':time.monotonic()-started,
         'max_output_tokens':16,'paid_provider_called':False,'Lean_executed':False,'rfl_is_unverified_draft':True,**FALSE})
    print(json.dumps({'inference_response_received':True,'wall_seconds':time.monotonic()-started,
                       'completion':result['choices'][0].get('message',{}).get('content'),**FALSE}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('download','verify','serve','smoke','status'));a=parser.parse_args()
    ROOT.mkdir(mode=0o700,exist_ok=True)
    require(not ROOT.is_symlink() and ROOT.stat().st_uid==os.getuid(),'Use only the explicit owned storage directory')
    if a.phase=='status':
        path=ROOT/(MODEL_NAME+'.partial');print(json.dumps({'partial_bytes':path.stat().st_size if path.exists() else None,'model_bytes':MODEL_BYTES,'ready_receipt_present':(ROOT/'server-ready.json').exists(),**FALSE}));return
    globals()[a.phase]()


if __name__=='__main__':main()
