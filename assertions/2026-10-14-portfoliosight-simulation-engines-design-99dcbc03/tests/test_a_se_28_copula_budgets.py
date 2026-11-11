# ruff: noqa: E501
"""A-SE-28 contract: frozen real workload on explicitly configured isolated KS-001.

SSH transport attests host; container cgroups and source hashes are inspected.
All mutations are confined to a temporary copied store. Full 12-tensor nightly
starts without fits/shocks. Actual HTTP first-load and warm copula responses are
timed; no recorded-JSON host claims or laptop proxy timing can pass.
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
    """Use project dependencies while importing product exclusively from this run checkout."""
    try:
        importlib.import_module("numpy")
        importlib.import_module("pandas")
    except ImportError:
        main = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
            ).strip()
        )
        if not main.is_absolute():
            main = ROOT / main
        python = main.resolve().parent / ".venv/bin/python"
        assert python.exists(), (
            "Project runtime missing; this gate cannot pass without its dependencies"
        )
        assert not os.environ.get("A_SE_REEXEC"), (
            "Project runtime still lacks required dependencies"
        )
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "A_SE_REEXEC": "1",
            },
            capture_output=True,
            text=True,
            timeout=21600,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return False
    package = importlib.import_module("portfoliosight")
    assert Path(package.__file__).resolve().is_relative_to(ROOT), (
        "Imported another editable checkout"
    )
    return True


def _module(name):
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        raise AssertionError(f"Required implementation {name} is unavailable: {exc}") from exc
    assert Path(module.__file__).resolve().is_relative_to(ROOT), (
        f"{name} came from another checkout"
    )
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
os.environ.update(PS_ENGINES='replay,garch,copula',PS_ENGINES_CUSTOM='replay,garch',PS_GATE_SECRET='frozen-target-benchmark-local-gate',PS_BUILD_WORKERS='4',PS_GRID_NX='48',PS_GRID_NY='32',PS_GRID_LEVELS='12')
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
consumed=[];request_models={};cold_models={};observation_ns=0;real_full=builder.build_tensor_full
# Observe models at the actual builder seam; never replace its calculation.
def observed(*a,**kw):
 global observation_ns
 result=real_full(*a,**kw)
 observer_start=time.perf_counter_ns()
 if result.tensor['lookback']['id']=='5y':request_models[result.tensor['universe']['preset_id']]=result.models['copula']
 for e,m in result.models.items():
  if e in ('garch','copula'):assert m.panel.shape[:2]==(2000,252);descriptor={'engine':e,'shape':list(m.panel.shape),'dtype':str(m.panel.dtype),'sha256':hashlib.sha256(np.ascontiguousarray(m.panel).tobytes()).hexdigest()}
  else:assert m.counts.shape[0]==2000 and np.all(m.counts.sum(axis=1)==252);descriptor={'engine':e,'shape':[2000,252,len(m.mu_s)],'counts_shape':list(m.counts.shape),'sha256':hashlib.sha256(np.ascontiguousarray(m.counts).tobytes()).hexdigest()}
  if e in ('garch','copula'):
   artifact=result.artifacts['garch'];funds=list(artifact.funds)
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
 store=fresh_store(temp/'cold-store');os.environ['PS_CACHE_DIR']=str(temp/'cold-cache')
 guide=next(p for p in definitions if p.id=='guide2017');assert len(guide.funds)==23
 policy=presets.preset_funds(guide);uhash=presets.universe_hash(policy)
 assert not store.list('models/'),'Cold-fit measurement cannot start with artifact hits'
 fit_calls=[];real_fit=builder.fit_shape
 def fit(*a,**kw):fit_calls.append(True);return real_fit(*a,**kw)
 builder.fit_shape=fit
 cold_fit_calls=0
 # Use the real two-preset/six-lookback nightly build loop with empty tensor keys.
 store=fresh_store(temp/'nightly-store');os.environ['PS_CACHE_DIR']=str(temp/'nightly-cache');assert not store.list('models/') and not store.list('tensors/');observed_before=observation_ns
 errors=[];started=time.perf_counter_ns();seconds,built,complete=nightly._build_presets(store,generation,queue.build_job,errors);nightly_ns=time.perf_counter_ns()-started-(observation_ns-observed_before);nightly_fit_calls=len(fit_calls)-cold_fit_calls;assert nightly_fit_calls>0
 assert complete and not errors and built=={'guide2017':6,'tsp':6},(built,errors)
 assert len(store.list('tensors/'+generation+'/'))==12
 tensor_evidence=[]
 for key in store.list('tensors/'+generation+'/'):
  item=sm.get_json(store,key);assert set(item['frontier']['ranges'])>={'replay','garch','copula'} and len(item['frontier']['w'])==48
  tensor_evidence.append({'menu':item['universe']['preset_id'],'lookback':item['lookback']['id'],'fund_ids':[fund['id'] for fund in item['universe']['funds']],'shape_rows':item['shape']['rows'],'funds':item['shape']['funds']})
 assert consumed and {d['engine'] for d in consumed}=={'replay','garch','copula'},'No actual full-path model consumption observed'
 fallback=[];warm=[];requests=[]
 for preset in definitions:
  policy=presets.preset_funds(preset);uhash=presets.universe_hash(policy)
  tensor=sm.get_json(store,presets.tensor_key(generation,uhash,'5y'))
  count=len(tensor['universe']['funds']);weights=np.arange(1,count+1)/np.arange(1,count+1).sum()
  requests.append((preset.id,{'generation':generation,'hash':uhash,'lookback':'5y','weights':weights.tolist(),'engine':'copula'}))
  fallback.extend({'id':f['id'],'status':f['status']} for f in tensor['shape']['funds'] if f['status']!='garch')
 os.environ['PS_CACHE_DIR']=str(temp/'empty-api-cache')
 reads=[]
 class CountingStore:
  def __getattr__(self,key):return getattr(store,key)
  def get(self,key):reads.append(key);return store.get(key)
 from portfoliosight.api import ranges as ar
 instances=[];original_models=ar.RangeModels.__init__
 def observed_models(self,*a,**k):original_models(self,*a,**k);instances.append(self)
 ar.RangeModels.__init__=observed_models
 with TestClient(create_app(store=CountingStore(),start_worker=False),raise_server_exceptions=False) as client:
  for menu,request in requests:
   expected_quantiles=np.percentile(_years(request_models[menu],request['weights']),[2.5,50,97.5],method='linear')
   for phase in ('first-load','warm'):
    before=len(reads);started=time.perf_counter_ns();answer=client.post('/v1/range',json=request,headers={'x-ps-gate':os.environ['PS_GATE_SECRET']});elapsed=time.perf_counter_ns()-started
    assert answer.status_code==200 and answer.json()['engine']=='copula',answer.text
    actual=answer.json();assert actual['bad']<actual['typical']<actual['good']
    assert np.allclose([actual[k] for k in ('bad','typical','good')],expected_quantiles,rtol=0,atol=5e-4)
    if phase=='first-load':assert any(k.endswith('copula_shocks.npy') for k in reads[before:]),'First artifact load was silently warmed'
    panels=instances[0]._panels;assert len(panels)<=2
    for model in panels.values():
     panel=model if isinstance(model,np.ndarray) else model.panel
     assert panel.dtype==np.float32 and panel.shape[:2]==(2000,252)
    warm.append({'menu':menu,'phase':phase,'engine':'copula','elapsed_ns':elapsed,'answer':actual,'expected':expected_quantiles.tolist(),'weights':request['weights']})
 assert fit_calls and {r['phase'] for r in warm}=={'first-load','warm'}
 cold_fit_calls=nightly_fit_calls
 assert all(hashlib.sha256(original.get(k)).hexdigest()==v for k,v in inputs.items()),'Benchmark modified original input store'
 print('FROZEN_BENCHMARK='+json.dumps({'revision':measured_revision,'source_tree_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'cpu_quota':4,'memory_bytes':memory,'input_sha256':inputs,'cold_fit_calls':cold_fit_calls,'nightly_fit_calls':nightly_fit_calls,'tensors':tensor_evidence,'nightly_ns':nightly_ns,'built':built,'warm':warm,'consumed':consumed,'fallbacks':fallback,'cache':'empty models before full nightly; new API cache before first copula requests'},allow_nan=False))

'''


def test_a_se_28_copula_target_budgets(tmp_path):
    if not _runtime():
        return
    import hashlib
    import shlex
    import time

    required = (
        "PS_KS001_SSH_HOST",
        "PS_KS001_BENCH_CONTAINER",
        "PS_KS001_REPO_DIR",
        "PS_KS001_INPUT_STORE",
    )
    missing = [k for k in required if not os.environ.get(k)]
    assert not missing, "Explicit isolated KS-001 benchmark context missing: " + ", ".join(missing)
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
    sm = _module("portfoliosight.data.store")
    local_store = sm.LocalStore(mirror)
    pointer = sm.get_json(local_store, "meta/current.json")
    presets = _module("portfoliosight.api.presets").preset_definitions()
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

    command = (
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
    start = time.perf_counter()
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host, command],
        input="",
        text=True,
        capture_output=True,
        timeout=1200,
    )
    elapsed = time.perf_counter() - start
    assert result.returncode == 0, result.stdout[-8000:] + result.stderr[-5000:]
    lines = result.stdout.splitlines()
    assert lines and lines[0].strip().lower() == "ks-001", "The actual SSH host was not KS-001"
    payloads = [line.split("=", 1)[1] for line in lines if line.startswith("FROZEN_BENCHMARK=")]
    assert len(payloads) == 1
    data = json.loads(payloads[0])
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", data["revision"], revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )
    assert data["source_tree_sha256"] == source_tree
    assert data["cpu_quota"] == 4 and data["memory_bytes"] == 1536 * 1024 * 1024
    assert data["cold_fit_calls"] > 0 and data["nightly_fit_calls"] > 0
    assert data["input_sha256"] == input_sha256
    assert {(t["menu"], t["lookback"]) for t in data["tensors"]} == {
        (menu, lb) for menu in ("guide2017", "tsp") for lb in ("1y", "2y", "3y", "5y", "10y", "ew")
    }
    assert 0 < data["nightly_ns"] <= 600_000_000_000
    assert data["built"] == {"guide2017": 6, "tsp": 6}
    assert len(data["consumed"]) >= 36 and {d["engine"] for d in data["consumed"]} == {
        "replay",
        "garch",
        "copula",
    }
    assert all(d["shape"][:2] == [2000, 252] and d["sha256"] for d in data["consumed"])
    requests = data["warm"]
    assert len(requests) == 4 and sum(r["phase"] == "first-load" for r in requests) == 2
    assert all(0 < r["elapsed_ns"] <= 10_000_000_000 for r in requests)
    assert (data["nightly_ns"] + sum(r["elapsed_ns"] for r in requests)) / 1e9 <= elapsed + 1
    # Runbook must carry the measured execution, not unrelated old timings.
    runbooks = list((ROOT / "docs").rglob("*runbook*.md"))
    text = "\n".join(p.read_text() for p in runbooks)
    assert source_tree in text and "KS-001" in text and "copula" in text.lower()
    import re

    recorded = []
    for block in re.findall(r"```json\s*(.*?)```", text, re.S):
        try:
            entry = json.loads(block)
        except json.JSONDecodeError:
            continue
        if entry.get("source_tree_sha256") == source_tree and entry.get("phase") == 3:
            recorded.append(entry)
    assert recorded, "Runbook needs a Phase 3 measured evidence record for this revision"
    entry = recorded[-1]
    measured = entry["revision"]
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", measured, revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )
    for name, digest in digests.items():
        historical = subprocess.run(
            ["git", "show", measured + ":" + name], cwd=ROOT, capture_output=True
        )
        assert (
            historical.returncode == 0 and hashlib.sha256(historical.stdout).hexdigest() == digest
        )
    assert 0 < entry["nightly_seconds"] <= 600
    assert entry["paths"] == 2000 and entry["horizon_days"] == 252
    assert 0 < entry["copula_first_load_seconds"] <= 10 and 0 < entry["copula_warm_seconds"] <= 10
    for fallback in data["fallbacks"]:
        assert fallback["id"] in text and fallback["status"] in text
    (tmp_path / "copula_target_budget.json").write_text(json.dumps(data, allow_nan=False))
