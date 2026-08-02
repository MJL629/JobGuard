"""
JobGuard 系统监控模块

纯 Python 实现，无外部依赖。
- 请求指标收集（延迟、状态码、QPS）
- LLM 调用追踪（token 用量、模型延迟）
- Prometheus 格式输出
"""

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RequestMetrics:
    """单次请求指标"""
    path: str
    method: str
    status_code: int
    duration_ms: float
    timestamp: float


class MetricsCollector:
    """线程安全的指标收集器（单例）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._requests: deque[RequestMetrics] = deque(maxlen=10000)
        self._llm_calls: deque[dict] = deque(maxlen=5000)
        self._errors: defaultdict[str, int] = defaultdict(int)
        self._request_count = 0
        self._llm_total_tokens = 0
        self._llm_call_count = 0
        self._llm_by_provider: defaultdict[str, dict] = defaultdict(
            lambda: {"calls": 0, "tokens": 0, "total_duration_ms": 0.0}
        )

    def record_request(self, path: str, method: str, status: int, duration_ms: float):
        """记录 HTTP 请求"""
        with self._lock:
            self._request_count += 1
            self._requests.append(RequestMetrics(
                path=path, method=method,
                status_code=status, duration_ms=duration_ms,
                timestamp=time.time(),
            ))

    def record_llm_call(self, provider: str, model: str, tokens: int, duration_ms: float):
        """记录 LLM 调用"""
        with self._lock:
            self._llm_call_count += 1
            self._llm_total_tokens += tokens
            self._llm_calls.append({
                "provider": provider, "model": model,
                "tokens": tokens, "duration_ms": duration_ms,
                "timestamp": time.time(),
            })
            p = self._llm_by_provider[provider]
            p["calls"] += 1
            p["tokens"] += tokens
            p["total_duration_ms"] += duration_ms

    def record_error(self, error_type: str, path: str):
        """记录错误"""
        with self._lock:
            self._errors[f"{error_type}:{path}"] += 1

    def get_summary(self) -> dict:
        """返回汇总指标"""
        with self._lock:
            now = time.time()
            uptime = now - self._start_time

            # 最近 1000 个请求的延迟统计
            recent = list(self._requests)[-1000:]
            durations = sorted([r.duration_ms for r in recent])

            by_path = defaultdict(int)
            by_status = defaultdict(int)
            for r in recent:
                by_path[r.path] += 1
                by_status[str(r.status_code)] += 1

            return {
                "uptime_seconds": round(uptime, 1),
                "requests": {
                    "total": self._request_count,
                    "by_path": dict(by_path),
                    "by_status": dict(by_status),
                },
                "latency": {
                    "p50_ms": self._percentile(durations, 50),
                    "p95_ms": self._percentile(durations, 95),
                    "p99_ms": self._percentile(durations, 99),
                    "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0,
                },
                "llm": {
                    "total_calls": self._llm_call_count,
                    "total_tokens": self._llm_total_tokens,
                    "by_provider": {
                        k: dict(v) for k, v in self._llm_by_provider.items()
                    },
                },
                "errors": {
                    "total": sum(self._errors.values()),
                    "by_type": dict(self._errors),
                },
                "qps": {
                    "last_1m": round(self._count_recent(60) / 60, 2),
                    "last_5m": round(self._count_recent(300) / 300, 2),
                },
            }

    def get_prometheus_format(self) -> str:
        """输出 Prometheus 文本格式"""
        s = self.get_summary()
        lines = [
            "# HELP jobguard_uptime_seconds Service uptime in seconds",
            "# TYPE jobguard_uptime_seconds gauge",
            f"jobguard_uptime_seconds {s['uptime_seconds']}",
            "",
            "# HELP jobguard_requests_total Total HTTP requests",
            "# TYPE jobguard_requests_total counter",
            f"jobguard_requests_total {s['requests']['total']}",
            "",
            "# HELP jobguard_llm_calls_total Total LLM API calls",
            "# TYPE jobguard_llm_calls_total counter",
            f"jobguard_llm_calls_total {s['llm']['total_calls']}",
            "",
            "# HELP jobguard_llm_tokens_total Total LLM tokens consumed",
            "# TYPE jobguard_llm_tokens_total counter",
            f"jobguard_llm_tokens_total {s['llm']['total_tokens']}",
            "",
            "# HELP jobguard_request_latency_ms Request latency in ms",
            "# TYPE jobguard_request_latency_ms gauge",
            f"jobguard_request_latency_ms{{quantile=\"0.50\"}} {s['latency']['p50_ms']}",
            f"jobguard_request_latency_ms{{quantile=\"0.95\"}} {s['latency']['p95_ms']}",
            f"jobguard_request_latency_ms{{quantile=\"0.99\"}} {s['latency']['p99_ms']}",
            "",
            "# HELP jobguard_errors_total Total errors",
            "# TYPE jobguard_errors_total counter",
            f"jobguard_errors_total {s['errors']['total']}",
        ]
        return "\n".join(lines) + "\n"

    # ─── 内部方法 ────────────────────────────────────────────────

    def _percentile(self, sorted_data: list[float], p: float) -> float:
        """计算百分位数"""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * p / 100.0
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        if f == c:
            return round(sorted_data[f], 1)
        return round(sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f), 1)

    def _count_recent(self, seconds: float) -> int:
        """统计最近 N 秒内的请求数"""
        cutoff = time.time() - seconds
        return sum(1 for r in self._requests if r.timestamp > cutoff)


# 全局单例
metrics = MetricsCollector()
