"""Resumable one-factor-at-a-time vLLM sweep for JobGuard."""
from __future__ import annotations
import argparse, asyncio, csv, json, os, signal, subprocess, time
from pathlib import Path
import httpx
from benchmark_vllm import run_level

BASE={"max_model_len":8192,"max_num_seqs":256,"prefix_caching":True}
SERVER_CONFIGS=[BASE,
    *[{**BASE,"max_model_len":v} for v in (2048,4096,16384)],
    *[{**BASE,"max_num_seqs":v} for v in (8,32,64,128)],
    {**BASE,"prefix_caching":False}]
def key(c): return f'len{c["max_model_len"]}_seq{c["max_num_seqs"]}_prefix{int(c["prefix_caching"])}'
def gpu_mb():
    out=subprocess.check_output(["nvidia-smi","--query-compute-apps=used_memory","--format=csv,noheader,nounits"],text=True).splitlines()
    return sum(int(x.strip()) for x in out if x.strip())
def stop(p):
    if p.poll() is None:
        try: os.killpg(p.pid,signal.SIGTERM); p.wait(20)
        except Exception:
            try: os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError: pass
async def ready(url,p,timeout=240):
    end=time.monotonic()+timeout
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic()<end:
            if p.poll() is not None: raise RuntimeError(f"vLLM exited {p.returncode}")
            try:
                if (await client.get(url+"/models")).status_code==200:return
            except httpx.HTTPError: pass
            await asyncio.sleep(2)
    raise TimeoutError("vLLM readiness timeout")
def save(rows,out):
    out.mkdir(parents=True,exist_ok=True)
    (out/"metrics.json").write_text(json.dumps({"method":"OFAT","baseline":BASE,"rows":rows},ensure_ascii=False,indent=2),encoding="utf-8")
    fields=sorted({k for r in rows for k in r})
    with (out/"metrics.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
async def run(a):
    a.output.mkdir(parents=True,exist_ok=True); metrics=a.output/"metrics.json"
    rows=json.loads(metrics.read_text(encoding="utf-8"))["rows"] if metrics.exists() else []
    done={(r.get("config_key"),r.get("concurrency")) for r in rows if r.get("status")=="ok"}
    for config in SERVER_CONFIGS:
        levels=(1,4,8,16,32) if config==BASE else (16,)
        if all((key(config),c) in done for c in levels): continue
        log=a.output/f'{key(config)}.log'; cmd=["vllm","serve",str(a.model),"--served-model-name",a.name,"--host","127.0.0.1","--port",str(a.port),"--dtype","bfloat16","--max-model-len",str(config["max_model_len"]),"--max-num-seqs",str(config["max_num_seqs"]),"--gpu-memory-utilization",str(a.gpu_util)]
        if config["prefix_caching"]:cmd.append("--enable-prefix-caching")
        with log.open("a",encoding="utf-8") as stream:
            p=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,text=True)
            try:
                await ready(a.url,p); memory=gpu_mb()
                for concurrency in levels:
                    if (key(config),concurrency) in done:continue
                    try: row={"config_key":key(config),**config,"status":"ok","gpu_memory_used_mb":memory,**await run_level(a.url,a.name,concurrency)}
                    except Exception as exc: row={"config_key":key(config),**config,"concurrency":concurrency,"status":"error","error":repr(exc)}
                    rows.append(row);save(rows,a.output);print(json.dumps(row),flush=True)
            except Exception as exc:
                rows.append({"config_key":key(config),**config,"status":"server_error","error":repr(exc)});save(rows,a.output)
            finally:stop(p);await asyncio.sleep(4)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--model",type=Path,required=True);p.add_argument("--name",default="qwen2.5-7b");p.add_argument("--port",type=int,default=6006);p.add_argument("--gpu-util",type=float,default=.9);p.add_argument("--output",type=Path,default=Path("../experiments/vllm"));a=p.parse_args();a.url=f"http://127.0.0.1:{a.port}/v1";asyncio.run(run(a))
