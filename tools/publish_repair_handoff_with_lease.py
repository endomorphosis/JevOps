#!/usr/bin/env python3
"""Publish a validated operational handoff using only a live-gated timed queue lease."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

import publish_repair_handoff_when_idle as publisher

PUBLISHER_SHA256 = 'd02b049a2b71cff2df6b6aafb4aa06d44e5858cccd5807048004c32523c98dde'
ROOT = Path(__file__).resolve().parents[1]


def pinned_publisher():
    path = Path(__file__).with_name('publish_repair_handoff_when_idle.py')
    publisher.require(Path(publisher.__file__).resolve()==path.resolve()
        and hashlib.sha256(publisher.read_owned(path)[0]).hexdigest()==PUBLISHER_SHA256,
        'Exact unchanged publication helper required')


def registration_proof(root, cfg, registration):
    """Keep exact returned custody available even if later proof validation fails."""
    token = registration['token']
    publisher.require(type(token) is str and publisher.re.fullmatch('[0-9a-f]{32}',token),
                      'Exact registered queue token required')
    hold = cfg.state_dir/'hold'
    archive = cfg.state_dir/'expired-queue-holds'/(token+'.hold')
    return dict(schema=publisher.LEASE_SCHEMA,path=str(hold.relative_to(root)),
        device=registration['device'],inode=registration['inode'],sha256=registration['body_sha256'],
        token=token,release_archive=str(archive.relative_to(root)))


def write_proof(path, value):
    raw = (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def describe(error):
    try:
        return type(error).__name__+': '+str(error)
    except BaseException:
        return type(error).__name__


def is_control(error):
    return not isinstance(error,Exception) or isinstance(error,InterruptedError)


def publish_with_lease(root, request_ref, *, timeout=1200, once=False):
    result = dict(schema='jevops.timed-repair-handoff-publication.v1',published=False,**publisher.FLAGS)
    registration = lease = binding = None
    pending = None
    registration_attempted = False
    code = 1
    try:
        publisher.require(type(timeout) is int and 1<=timeout<=1770,'Timeout must be 1..1770seconds')
        deadline = time.monotonic()+timeout
        pinned_publisher()
        root = Path(root).resolve(strict=True)
        binding = publisher.idle.scope(root)
        external = Path(binding['supervisor']['accelerator_source']).resolve(strict=True)
        publisher.request_input(root,request_ref,external_preserve_root=external,deadline=deadline)
        publisher.in_time(deadline)
        publisher.idle.unchanged_scope(binding)
        pinned_publisher()
        cfg,native = binding['native_cfg'],binding['native']
        # Signal restoration occurs only after trusted returned custody is assigned.
        with publisher.hold_commit():
            registration_attempted = True
            registration = native.register_queue_hold(cfg,'bounded operational handoff publication',timeout+30)
            lease = registration_proof(root,cfg,registration)
        projected = native.publisher_queue_hold_proof(cfg,registration)
        publisher.require(projected==lease,'Native timed lease projection differs')
        proof_path = publisher.path_in(root,request_ref['path']).parent/('.repair-queue-proof-'+lease['token']+'.json')
        proof_ref = dict(path=str(proof_path.relative_to(root)),sha256=write_proof(proof_path,lease))
        result.update(lease=proof_ref,queue_hold_token=lease['token'],expires_at=registration['expires_at'])
        publisher.in_time(deadline)
        remaining = math.floor(deadline-time.monotonic())
        if remaining<1:raise TimeoutError('No bounded publication time remains')
        actual,code = publisher.publish_when_idle(root,request_ref,proof_ref,timeout=remaining,once=once)
        result.update(actual)
    except BaseException as error:
        pending = error
        result.update(error_type=type(error).__name__,error=describe(error))
        try:
            partial=getattr(error,'publication_result',{})
            if type(partial) is dict:result.update(partial)
        except BaseException:pass
        if is_control(error):
            try:error.publication_result=result
            except BaseException:pass
            raise
        code = 75 if isinstance(error,TimeoutError) else 1
    finally:
        if registration is not None:
            cleanup_error = None
            try:
                if lease is None:lease=registration_proof(root,binding['native_cfg'],registration)
                result['queue_hold_released']=publisher.release_queue_hold(root,lease)
            except BaseException as error:
                cleanup_error=error
                result.update(queue_hold_released=False,queue_hold_release_error=describe(error))
            if not result.get('queue_hold_released'):
                authenticated = False
                try:
                    current=binding['native'].review_queue_hold(binding['native_cfg'],time.time())
                    authenticated=(current['status'] in ('active','expired') and all(
                        current.get(key)==registration.get(key) for key in ('token','device','inode','body_sha256','created_at','expires_at')))
                except BaseException as error:
                    if cleanup_error is None:cleanup_error=error
                result.update(automatic_expiry_fallback=authenticated,attention_required=not authenticated)
                if code==0:code=1
            else:
                result['automatic_expiry_fallback']=False
            if cleanup_error is not None and is_control(cleanup_error) and (pending is None or not is_control(pending)):
                try:cleanup_error.publication_result=result
                except BaseException:pass
                raise cleanup_error
        elif registration_attempted:
            # No returned custody: never adopt a lease another concurrent caller may own.
            result.update(registration_incomplete=True,queue_hold_cleanup_deferred=True,
                          queue_hold_released=None,automatic_expiry_fallback=None)
    return result,code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root',type=Path,default=ROOT)
    parser.add_argument('--request',required=True)
    parser.add_argument('--request-sha256',required=True)
    parser.add_argument('--timeout',type=int,default=1200)
    args=parser.parse_args(argv)
    previous={}
    def interrupt(_sig,_frame):raise KeyboardInterrupt('Timed publication interrupted')
    try:
        for sig in (signal.SIGTERM,signal.SIGINT):previous[sig]=signal.signal(sig,interrupt)
        try:
            result,code=publish_with_lease(args.repo_root,dict(path=args.request,sha256=args.request_sha256),timeout=args.timeout)
        except BaseException as error:
            try:print(json.dumps(getattr(error,'publication_result',dict(published=False,error=describe(error))),sort_keys=True),file=sys.stderr)
            except BaseException:pass
            raise
        print(json.dumps(result,sort_keys=True));return code
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


if __name__=='__main__':raise SystemExit(main())
