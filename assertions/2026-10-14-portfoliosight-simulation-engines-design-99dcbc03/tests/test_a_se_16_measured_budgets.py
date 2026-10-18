# ruff: noqa: E501 -- embedded runtime programs retain their native source layout.
"""A-SE-16: dispatch frozen measured workload to the explicitly configured KS-001 container.
No automatic credentials, production-store writes, deployment, laptop timing proxy or saved
self-reported timing field. Operator prerequisites: PS_KS001_SSH_HOST,
PS_KS001_BENCH_CONTAINER, PS_KS001_REPO_DIR, PS_KS001_INPUT_STORE (read-only source).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _runtime():
    """Run this frozen file in installed dependencies, importing this run's source."""
    roots = [ROOT]
    if (ROOT / ".git").is_file():
        roots.append(Path((ROOT / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    python = next(
        (p / ".venv/bin/python" for p in roots if (p / ".venv/bin/python").exists()), None
    )
    if python and Path(sys.prefix).resolve() != python.parents[1].resolve():
        result = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--noconftest", "-p", "no:cacheprovider", __file__],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            },
            text=True,
            capture_output=True,
            timeout=1200,
        )
        assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-3000:]
        return False
    return True


def _product(name, attr=None):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(f"Required runtime {name} is unavailable: {type(exc).__name__}: {exc}")
    if name.startswith(("portfoliosight", "scripts")):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            f"Imported foreign source: {module.__file__}"
        )
    if attr is not None:
        if not hasattr(module, attr):
            pytest.fail(f"Missing required runtime interface {name}.{attr}")
        return getattr(module, attr)
    return module


REMOTE_SOURCE = r'''
import hashlib,json,os,pathlib,subprocess,sys,tempfile,time,socket
root=pathlib.Path(sys.argv[1]).resolve();sys.path.insert(0,str(root));source=pathlib.Path(sys.argv[2]);expected=json.loads(sys.argv[3]);revision=sys.argv[4];expected_inputs=json.loads(sys.argv[5])
measured_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
for name,digest in expected.items(): assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Target source differs: '+name
quota,period=pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().split();memory=int(pathlib.Path('/sys/fs/cgroup/memory.max').read_text())
assert quota!='max' and int(quota)/int(period)==4 and memory==1536*1024*1024,'Benchmark requires actual four-vCPU/1536MB container'
def blocked(*a,**k):raise AssertionError('No provider/network calls in target benchmark')
socket.create_connection=blocked;socket.socket.connect=blocked
os.environ.update(PS_ENGINES='replay,garch',PS_ENGINES_CUSTOM='replay,garch',PS_GATE_SECRET='frozen-target-benchmark-local-gate',PS_BUILD_WORKERS='4',PS_GRID_NX='48',PS_GRID_NY='32',PS_GRID_LEVELS='12')
import numpy as np
import pandas as pd
from portfoliosight.data import store as sm
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine import builder
from portfoliosight.jobs import build as jobs,nightly
from portfoliosight.api import queue,presets
from portfoliosight.api.app import create_app
from fastapi.testclient import TestClient
for module in (sm,builder,jobs,nightly):assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert hasattr(builder,'build_tensor_full'),'Engine-aware builder absent'
original=sm.LocalStore(source);pointer=sm.get_json(original,'meta/current.json');input_generation=pointer['generation'];meta=sm.get_json(original,jobs.generation_key(input_generation));generation=meta['asof']+'-'+ENGINE_VERSION
assert source.is_dir();definitions=presets.preset_definitions();assert {p.id for p in definitions}=={'guide2017','tsp'}
ids={f for p in definitions for f in p.funds}|{'SGOV','SHV','TSP-G'}
input_keys=list(expected_inputs);assert set(input_keys)>={'meta/manifest.json','meta/current.json',jobs.generation_key(input_generation)}|{sm.record_key(fid) for fid in ids if fid not in {'SGOV','SHV'}}
inputs={k:hashlib.sha256(original.get(k)).hexdigest() for k in input_keys};assert inputs==expected_inputs,'Target records differ from attested local backup'
consumed=[];cold_models={};observation_ns=0;real_full=builder.build_tensor_full
# Observe models at the actual builder seam; never replace its calculation.
def observed(*a,**kw):
 global observation_ns
 result=real_full(*a,**kw)
 observer_start=time.perf_counter_ns()
 if not cold_models:cold_models.update(result.models)
 for e,m in result.models.items():
  if e=='garch':assert m.panel.shape[:2]==(2000,252);descriptor={'engine':e,'shape':list(m.panel.shape),'dtype':str(m.panel.dtype),'sha256':hashlib.sha256(np.ascontiguousarray(m.panel).tobytes()).hexdigest()}
  else:assert m.counts.shape[0]==2000 and np.all(m.counts.sum(axis=1)==252);descriptor={'engine':e,'shape':[2000,252,len(m.mu_s)],'counts_shape':list(m.counts.shape),'sha256':hashlib.sha256(np.ascontiguousarray(m.counts).tobytes()).hexdigest()}
  if e=='garch':
   artifact=result.artifacts[e];funds=list(artifact.funds)
   prices=pd.DataFrame({fid:sm.get_record(original,fid).set_index('date')['tr_index'] for fid in funds}).sort_index()
   returns=(prices/prices.shift(1)-1).loc[:meta['asof']];panel=returns.loc[returns.notna().any(axis=1)].tail(2520)
   assert artifact.rows==len(panel) and list(artifact.n_obs)==panel.notna().sum().tolist()
   digest=hashlib.sha256();digest.update('\x1f'.join(funds).encode());digest.update(b'\x1e');digest.update('\x1f'.join(stamp.date().isoformat() for stamp in panel.index).encode());digest.update(b'\x1e');digest.update(np.ascontiguousarray(panel.to_numpy(),dtype='<f8').tobytes())
   assert artifact.sample_sha256==digest.hexdigest()
   descriptor.update(shape_rows=len(panel),fund_ids=funds,n_obs=list(artifact.n_obs),statuses=list(artifact.status))
  consumed.append(descriptor)
 observation_ns+=time.perf_counter_ns()-observer_start
 return result
builder.build_tensor_full=observed
for module in (jobs,):
 if getattr(module,'build_tensor_full',None) is real_full:module.build_tensor_full=observed
def _years(model, weights):
    """Independent §4.5 oracle from the exact arrays the builder consumed, no range call."""
    w = np.asarray(weights, dtype=float)
    target = float(np.asarray(model.mu_s) @ w) / 252
    if getattr(model, "engine", "replay") == "replay":
        daily = np.asarray(model.sample) @ w
        growth = 1 + daily - daily.mean() + target
        assert np.all(growth > 0)
        assert model.counts.shape[0] == 2000
        np.testing.assert_array_equal(model.counts.sum(axis=1), np.full(2000, 252))
        return np.expm1(np.asarray(model.counts) @ np.log(growth))
    panel = np.asarray(model.panel, dtype=float)
    assert panel.shape[:2] == (2000, 252)
    flat = panel.reshape(-1, panel.shape[-1])
    mean, sd = flat.mean(axis=0), flat.std(axis=0, ddof=0)
    m = np.asarray(model.mu_s) / 252
    v = np.log1p(np.diag(model.cov) / 252 / (1 + m) ** 2)
    levelled = np.empty_like(flat)
    for n in range(flat.shape[1]):
        if sd[n] <= 64 * np.finfo(float).eps * max(1., abs(mean[n])):
            levelled[:, n] = m[n]
        else:
            levelled[:, n] = np.expm1(np.log1p(m[n]) - v[n] / 2 + (flat[:, n] - mean[n]) * np.sqrt(v[n]) / sd[n])
    y = levelled @ w
    spread = y.std(ddof=0)
    sigma = float(np.sqrt(w @ np.asarray(model.cov) @ w)) / np.sqrt(252)
    daily = np.full_like(y, target) if spread <= 1e-15 else target + (y - y.mean()) * sigma / spread
    daily = daily.reshape(2000, 252)
    ruined = (daily <= -1).any(axis=1)
    years = np.full(2000, -1.)
    years[~ruined] = np.expm1(np.log1p(daily[~ruined]).sum(axis=1))
    return years


with tempfile.TemporaryDirectory(prefix='frozen-engine-benchmark-') as temp:
 temp=pathlib.Path(temp)
 def fresh_store(path):
  target=sm.LocalStore(path)
  for key in input_keys:target.put(key,original.get(key))
  sm.put_json(target,jobs.generation_key(generation),{'generation':generation,'asof':meta['asof'],'engine_version':ENGINE_VERSION})
  sm.put_json(target,'meta/current.json',{'generation':generation})
  return target
 cache_before={}
 store=fresh_store(temp/'cold-store');os.environ['PS_CACHE_DIR']=str(temp/'cold-cache')
 cache_before['cold_models']=store.list('models/')
 guide=next(p for p in definitions if p.id=='guide2017');assert len(guide.funds)==23
 policy=presets.preset_funds(guide);uhash=presets.universe_hash(policy)
 assert not cache_before['cold_models'],'Cold-fit measurement cannot start with artifact hits'
 fit_calls=[];real_fit=builder.fit_shape
 def fit(*a,**kw):fit_calls.append(True);return real_fit(*a,**kw)
 builder.fit_shape=fit
 observed_before=observation_ns;started=time.perf_counter_ns();cold=jobs.build_from_store(store,generation=generation,funds=policy,lookback='5y',cache_dir=temp/'cold-cache',universe_name=guide.name,preset_id=guide.id,nx=48,ny=32,levels=12);cold_ns=time.perf_counter_ns()-started-(observation_ns-observed_before);cold_fit_calls=len(fit_calls)
 assert fit_calls and set(cold['frontier']['ranges'])>={'replay','garch'}
 # Use the real two-preset/six-lookback nightly build loop with empty tensor keys.
 store=fresh_store(temp/'nightly-store');os.environ['PS_CACHE_DIR']=str(temp/'nightly-cache');cache_before['nightly_models']=store.list('models/');cache_before['nightly_tensors']=store.list('tensors/');assert not cache_before['nightly_models'] and not cache_before['nightly_tensors'];observed_before=observation_ns
 errors=[];started=time.perf_counter_ns();seconds,built,complete=nightly._build_presets(store,generation,queue.build_job,errors);nightly_ns=time.perf_counter_ns()-started-(observation_ns-observed_before);nightly_fit_calls=len(fit_calls)-cold_fit_calls;assert nightly_fit_calls>0
 assert complete and not errors and built=={'guide2017':6,'tsp':6},(built,errors)
 assert len(store.list('tensors/'+generation+'/'))==12
 tensor_evidence=[]
 for key in store.list('tensors/'+generation+'/'):
  item=sm.get_json(store,key);assert set(item['frontier']['ranges'])>={'replay','garch'} and len(item['frontier']['w'])==48
  tensor_evidence.append({'menu':item['universe']['preset_id'],'lookback':item['lookback']['id'],'fund_ids':[fund['id'] for fund in item['universe']['funds']],'shape_rows':item['shape']['rows'],'funds':item['shape']['funds']})
 assert consumed and {d['engine'] for d in consumed}=={'replay','garch'},'No actual full-path model consumption observed'
 tensor=sm.get_json(store,presets.tensor_key(generation,uhash,'5y'))
 request={'generation':generation,'hash':uhash,'lookback':'5y','weights':(np.arange(1,24)/np.arange(1,24).sum()).tolist()}
 header={'x-ps-gate':os.environ['PS_GATE_SECRET']};warm=[]
 with TestClient(create_app(store=store,start_worker=False),raise_server_exceptions=False) as client:
  assert not client.app.state.queue._running if hasattr(client.app.state.queue,'_running') else True
  for e in ('replay','garch'):
   initial=client.post('/v1/range',json={**request,'engine':e},headers=header);assert initial.status_code==200,initial.text
   for shift in (0,1,2):
    w=np.roll(np.array(request['weights']),shift);started=time.perf_counter_ns();answer=client.post('/v1/range',json={**request,'weights':w.tolist(),'engine':e},headers=header);elapsed=time.perf_counter_ns()-started
    assert answer.status_code==200 and answer.json()['engine']==e and answer.json()['bad']<answer.json()['typical']<answer.json()['good'];expected_quantiles=np.percentile(_years(cold_models[e],w),[2.5,50,97.5],method='linear');assert np.allclose([answer.json()[k] for k in ('bad','typical','good')],expected_quantiles,atol=3e-5,rtol=3e-4);warm.append({'expected':expected_quantiles.tolist(),'engine':e,'elapsed_ns':elapsed,'answer':answer.json(),'weights':w.tolist()})
 fallback=[{'id':f['id'],'status':f['status']} for f in cold['shape']['funds'] if f['status']!='garch']
 assert all(hashlib.sha256(original.get(k)).hexdigest()==v for k,v in inputs.items()),'Benchmark modified original input store'
 print('FROZEN_BENCHMARK='+json.dumps({'revision':measured_revision,'source_tree_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'cpu_quota':4,'memory_bytes':memory,'input_sha256':inputs,'cold_fit_calls':cold_fit_calls,'nightly_fit_calls':nightly_fit_calls,'tensors':tensor_evidence,'cold_ns':cold_ns,'nightly_ns':nightly_ns,'built':built,'warm':warm,'consumed':consumed,'cache_before':cache_before,'fallbacks':fallback,'cache':'cold fit then nightly shared artifacts; warm HTTP after first engine request'},allow_nan=False))
'''


def test_a_se_16_target_measured_phase_one_budgets(tmp_path):
    if not _runtime():
        return
    import hashlib
    import re
    import shlex
    import time

    required = (
        "PS_KS001_SSH_HOST",
        "PS_KS001_BENCH_CONTAINER",
        "PS_KS001_REPO_DIR",
        "PS_KS001_INPUT_STORE",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        pytest.fail("A-SE-16 requires explicit target benchmark context: " + ", ".join(missing))
    host, container, remote_root, source = [os.environ[k] for k in required]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = [
        p for parent in ("portfoliosight", "qse", "scripts") for p in (ROOT / parent).rglob("*.py")
    ]
    files += [
        ROOT / name
        for name in (
            "pyproject.toml",
            "uv.lock",
            "requirements.lock",
            "deploy/Dockerfile",
            "data/presets.json",
            "qse/qse.lock.json",
            "data/universes/tiers.json",
        )
        if (ROOT / name).exists()
    ]
    digests = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source_tree = hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    mirror = Path(os.environ.get("PS_ENGINE_VALIDATION_STORE", "/mnt/d/portfoliosight-data"))
    if not mirror.is_dir():
        pytest.fail(
            "Budget proof needs the attested local real-data backup, not synthetic timing inputs"
        )
    sm = _product("portfoliosight.data.store")
    local_store = sm.LocalStore(mirror)
    pointer = sm.get_json(local_store, "meta/current.json")
    presets = _product("portfoliosight.api.presets").preset_definitions()
    funds = {fid for preset in presets for fid in preset.funds}
    keys = [
        "meta/current.json",
        "meta/manifest.json",
        "meta/" + pointer["generation"] + "/generation.json",
    ]
    keys += [
        sm.record_key(fid)
        for fid in sorted(funds | {"SGOV", "SHV", "TSP-G"})
        if local_store.exists(sm.record_key(fid))
    ]
    assert {sm.record_key(fid) for fid in funds} <= set(keys)
    input_sha256 = {key: hashlib.sha256(local_store.get(key)).hexdigest() for key in keys}
    # The remote hostname comes from SSH's actual host, then the cgroup limits are read in-container.
    remote_command = (
        "hostname; exec docker exec -i "
        + shlex.quote(container)
        + " python -c "
        + shlex.quote(REMOTE_SOURCE)
        + " "
        + " ".join(
            shlex.quote(v)
            for v in (remote_root, source, json.dumps(digests), revision, json.dumps(input_sha256))
        )
    )
    started = time.perf_counter()
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host, remote_command],
        input="",
        text=True,
        capture_output=True,
        timeout=1200,
    )
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stdout[-8000:] + result.stderr[-5000:]
    lines = result.stdout.splitlines()
    assert lines and lines[0].strip().lower() == "ks-001", "Benchmark ran on another host"
    markers = [line.split("=", 1)[1] for line in lines if line.startswith("FROZEN_BENCHMARK=")]
    assert len(markers) == 1, "No uniquely completed frozen target workload"
    data = json.loads(markers[0])
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", data["revision"], revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    ), "Measured target revision is not an ancestor of this run"
    assert data["source_tree_sha256"] == source_tree
    assert data["cpu_quota"] == 4 and data["memory_bytes"] == 1536 * 1024 * 1024
    assert data["input_sha256"] == input_sha256 and data["cold_fit_calls"] >= 1
    assert data["nightly_fit_calls"] >= 1
    assert not data["cache_before"]["cold_models"], "Cold-fit artifact cache was warm"
    assert not data["cache_before"]["nightly_models"], "Nightly model artifacts were prewarmed"
    assert not data["cache_before"]["nightly_tensors"], "Nightly tensors were already built"
    requested_engines = {"replay", "garch"}
    consumed_engines = {descriptor["engine"] for descriptor in data["consumed"]}
    assert not requested_engines - consumed_engines, "Requested engine workload was omitted"
    assert not consumed_engines - requested_engines, "Unrequested engines contaminated timing"
    assert {(t["menu"], t["lookback"]) for t in data["tensors"]} == {
        (menu, lookback)
        for menu in ("guide2017", "tsp")
        for lookback in ("1y", "2y", "3y", "5y", "10y", "ew")
    }
    for descriptor in data["consumed"]:
        if descriptor["engine"] == "garch":
            assert 126 <= descriptor["shape_rows"] <= 2520
            assert (
                len(descriptor["fund_ids"])
                == len(descriptor["n_obs"])
                == len(descriptor["statuses"])
            )
            assert all(0 < n <= descriptor["shape_rows"] for n in descriptor["n_obs"])
    assert 0 < data["cold_ns"] <= 30_000_000_000
    assert 0 < data["nightly_ns"] <= 600_000_000_000
    assert data["built"] == {"guide2017": 6, "tsp": 6}
    assert len(data["warm"]) == 6 and {r["engine"] for r in data["warm"]} == {"replay", "garch"}
    assert all(0 < r["elapsed_ns"] < 1_000_000_000 for r in data["warm"])
    total_ns = data["cold_ns"] + data["nightly_ns"] + sum(r["elapsed_ns"] for r in data["warm"])
    assert total_ns / 1e9 <= elapsed + 1, (
        "Recorded operation times exceed externally measured execution"
    )
    assert len(data["consumed"]) >= 24
    assert not [
        descriptor for descriptor in data["consumed"] if descriptor["shape"][:2] != [2000, 252]
    ], "Measured workload reduced or altered the required path count/horizon"
    runbooks = list((ROOT / "docs").rglob("*runbook*.md"))
    text = "\n".join(p.read_text() for p in runbooks)
    assert "KS-001" in text and source_tree in text
    # Documentation commits may follow measurement. Verify recorded revision/source independently.
    candidates = re.findall(r"\b[0-9a-f]{7,40}\b", text)
    matched_revision = False
    for recorded in candidates:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", recorded + "^{commit}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if resolved.returncode:
            continue
        measured = resolved.stdout.strip()
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", measured, revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode:
            continue
        bound = True
        for name, digest in digests.items():
            historical = subprocess.run(
                ["git", "show", measured + ":" + name],
                cwd=ROOT,
                capture_output=True,
            )
            if historical.returncode or hashlib.sha256(historical.stdout).hexdigest() != digest:
                bound = False
                break
        if bound:
            matched_revision = True
            break
    assert matched_revision, (
        "No recorded measured revision binds to the verified product source tree"
    )
    assert re.search(r"(?:2,000|2000).*(?:252)|252.*(?:2,000|2000)", text)
    assert re.search(r"warm|after (?:the )?first", text, re.I) and re.search(
        r"cold|fit", text, re.I
    )
    assert re.search(r"(?:build|nightly|range)[^\n]*\d+(?:\.\d+)?\s*(?:s|seconds)", text, re.I)
    for fallback in data["fallbacks"]:
        assert fallback["id"] in text, "Named fallback omitted from measured runbook evidence"
    (tmp_path / "ks001_measured_budget.json").write_text(json.dumps(data, allow_nan=False))
