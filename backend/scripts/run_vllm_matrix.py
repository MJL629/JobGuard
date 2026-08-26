"""Run the remaining vLLM configuration matrix without repeating equivalent rows."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import httpx

from benchmark_vllm import run_level


EXPERIMENTS = [
    {"name": "len4096_u90_prefix_on", "max_model_len": 4096, "gpu_memory_utilization": 0.90, "prefix_caching": True},
    {"name": "len8192_u90_prefix_on", "max_model_len": 8192, "gpu_memory_utilization": 0.90, "prefix_caching": True},
    {"name": "len16384_u90_prefix_on", "max_model_len": 16384, "gpu_memory_utilization": 0.90, "prefix_caching": True},
    {"name": "len8192_u80_prefix_on", "max_model_len": 8192, "gpu_memory_utilization": 0.80, "prefix_caching": True},
    {"name": "len8192_u95_prefix_on", "max_model_len": 8192, "gpu_memory_utilization": 0.95, "prefix_caching": True},
    {"name": "len8192_u90_prefix_off", "max_model_len": 8192, "gpu_memory_utilization": 0.90, "prefix_caching": False},
]


def gpu_memory_mb() -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=used_memory", "--format=csv,noheader,nounits"],
        text=True,
    ).strip().splitlines()
    return sum(int(value.strip()) for value in output if value.strip())


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def wait_ready(url: str, process: subprocess.Popen, timeout: int = 240) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"vLLM exited early with code {process.returncode}")
            try:
                response = await client.get(f"{url}/models")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
    raise TimeoutError("vLLM did not become ready")


async def run(args: argparse.Namespace) -> dict:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for experiment in EXPERIMENTS:
        log_path = args.output_dir / f"{experiment['name']}.log"
        command = [
            "vllm", "serve", str(args.model_path),
            "--served-model-name", args.served_model,
            "--host", "127.0.0.1",
            "--port", str(args.port),
            "--dtype", "bfloat16",
            "--max-model-len", str(experiment["max_model_len"]),
            "--gpu-memory-utilization", str(experiment["gpu_memory_utilization"]),
            "--max-num-seqs", "256",
        ]
        if experiment["prefix_caching"]:
            command.append("--enable-prefix-caching")

        started = time.time()
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                await wait_ready(args.url, process)
                memory = gpu_memory_mb()
                benchmark = await run_level(args.url, args.served_model, args.concurrency)
                row = {
                    **experiment,
                    "status": "ok",
                    "gpu_memory_used_mb": memory,
                    "startup_s": round(time.time() - started, 2),
                    **benchmark,
                    "log": str(log_path),
                }
            except Exception as exc:
                row = {
                    **experiment,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "log": str(log_path),
                }
            finally:
                stop_server(process)
                await asyncio.sleep(4)

        rows.append(row)
        output = {"model": str(args.model_path), "served_model": args.served_model, "rows": rows}
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return {"model": str(args.model_path), "served_model": args.served_model, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--served-model", default="qwen2.5-7b")
    parser.add_argument("--port", type=int, default=6006)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--output", type=Path, default=Path("backend/data/eval/vllm_matrix_v2.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("backend/data/eval/vllm_matrix_logs"))
    args = parser.parse_args()
    args.url = f"http://127.0.0.1:{args.port}/v1"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
