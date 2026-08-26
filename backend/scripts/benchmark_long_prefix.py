"""Compare vLLM prefix cache on/off using a genuinely long shared prefix."""
from __future__ import annotations
import argparse, asyncio, json, subprocess, time
from pathlib import Path
import benchmark_vllm
from run_vllm_deep import gpu_mb, ready, stop

LONG_PREFIX=("JobGuard岗位分析规则：只能依据原文抽取；缺失字段为null；技能保持数组；不要猜测公司、薪资、学历或经验；"
             "输出必须是单个合法JSON；检查字段类型和证据一致性。")*40
benchmark_vllm.PROMPT=LONG_PREFIX+"\n请返回company、position、skills、experience、education、location、salary。"
async def run(a):
    rows=[]
    for enabled in (False,True):
        log=a.output/f"long_prefix_{'on' if enabled else 'off'}.log";cmd=["vllm","serve",str(a.model),"--served-model-name",a.name,"--host","127.0.0.1","--port",str(a.port),"--dtype","bfloat16","--max-model-len","8192","--max-num-seqs","256","--gpu-memory-utilization","0.9"]
        if enabled:cmd.append("--enable-prefix-caching")
        with log.open("w",encoding="utf-8") as stream:
            p=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,text=True)
            try:
                await ready(a.url,p);memory=gpu_mb()
                await benchmark_vllm.run_level(a.url,a.name,1)  # warm shared prefix
                trials=[await benchmark_vllm.run_level(a.url,a.name,16) for _ in range(3)]
                keys=("request_throughput_rps","output_throughput_tps","ttft_ms_p50","ttft_ms_p95","tpot_ms_p50","tpot_ms_p95","e2e_ms_p50","e2e_ms_p95")
                rows.append({"prefix_caching":enabled,"shared_prefix_chars":len(LONG_PREFIX),"gpu_memory_used_mb":memory,**{k:round(sum(x[k] for x in trials)/len(trials),3) for k in keys},"trials":trials})
            finally:stop(p);await asyncio.sleep(4)
    a.output.mkdir(parents=True,exist_ok=True);(a.output/"long_prefix_metrics.json").write_text(json.dumps({"rows":rows},ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(rows))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--model",type=Path,required=True);p.add_argument("--name",default="qwen2.5-7b");p.add_argument("--port",type=int,default=6006);p.add_argument("--output",type=Path,default=Path("../experiments/vllm"));a=p.parse_args();a.url=f"http://127.0.0.1:{a.port}/v1";asyncio.run(run(a))
