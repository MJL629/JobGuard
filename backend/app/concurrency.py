"""
JobGuard 并发控制与限流模块

- RateLimiter: 基于 Token Bucket 的 API 限流
- ConcurrencyController: LLM 调用并发控制
- TimeoutManager: 超时管理
"""

import asyncio
import time
import threading
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Token Bucket 限流器 ──────────────────────────────────────────────

class TokenBucket:
    """
    Token Bucket 限流算法。

    用法:
        limiter = TokenBucket(rate=60, capacity=60)  # 每分钟 60 次
        if await limiter.acquire():
            # 处理请求
        else:
            # 限流拒绝
    """

    def __init__(self, rate: float, capacity: float):
        """
        Args:
            rate: 每秒填充 token 数
            capacity: 桶容量（允许突发）
        """
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        """补充 token"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self) -> bool:
        """尝试获取一个 token"""
        with self._lock:
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class RateLimiter:
    """
    多维度限流器。

    - 全局 QPS 限制
    - 每 IP 限制
    - 每用户限制
    """

    def __init__(
        self,
        global_rate: float = 100.0,     # 全局每秒 100 请求
        ip_rate: float = 20.0,           # 每 IP 每秒 20 请求
        user_rate: float = 10.0,         # 每用户每秒 10 请求
        capacity_multiplier: float = 2.0,  # 桶容量 = rate * multiplier
    ):
        self._global = TokenBucket(global_rate, global_rate * capacity_multiplier)
        self._per_ip: dict[str, TokenBucket] = {}
        self._per_user: dict[str, TokenBucket] = {}
        self._ip_rate = ip_rate
        self._user_rate = user_rate
        self._capacity_mult = capacity_multiplier
        self._lock = threading.Lock()

    async def check(self, ip: str = "unknown", user_id: str = "unknown") -> tuple[bool, str]:
        """
        检查是否允许请求。

        Returns:
            (allowed, reason) — reason 为空表示允许
        """
        # 全局限流
        if not await self._global.acquire():
            return False, "rate_limit_global"

        # IP 限流
        ip_bucket = self._get_or_create_ip_bucket(ip)
        if not await ip_bucket.acquire():
            return False, "rate_limit_ip"

        # 用户限流
        user_bucket = self._get_or_create_user_bucket(user_id)
        if not await user_bucket.acquire():
            return False, "rate_limit_user"

        return True, ""

    def _get_or_create_ip_bucket(self, ip: str) -> TokenBucket:
        with self._lock:
            if ip not in self._per_ip:
                self._per_ip[ip] = TokenBucket(
                    self._ip_rate, self._ip_rate * self._capacity_mult
                )
            return self._per_ip[ip]

    def _get_or_create_user_bucket(self, user_id: str) -> TokenBucket:
        with self._lock:
            if user_id not in self._per_user:
                self._per_user[user_id] = TokenBucket(
                    self._user_rate, self._user_rate * self._capacity_mult
                )
            return self._per_user[user_id]


# 全局限流器
rate_limiter = RateLimiter()


# ─── LLM 并发控制器 ──────────────────────────────────────────────────

class LLMConcurrencyController:
    """
    LLM API 调用并发控制。

    防止同时发起过多 LLM 请求导致：
    - API 速率限制
    - 内存溢出
    - 超时雪崩
    """

    def __init__(self, max_concurrent: int = 10):
        """
        Args:
            max_concurrent: 最大并发 LLM 调用数
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue_size = 0
        self._lock = threading.Lock()

    async def call(self, coro, provider: str = "unknown") -> any:
        """
        在并发控制下执行 LLM 调用。

        Usage:
            result = await controller.call(llm_gateway.chat(...), provider="zhipu")
        """
        with self._lock:
            self._queue_size += 1
            if self._queue_size > 20:
                logger.warning(
                    f"[Concurrency] LLM 调用队列积压: {self._queue_size}"
                )

        try:
            async with self._semaphore:
                with self._lock:
                    self._queue_size -= 1
                return await coro
        except Exception as e:
            with self._lock:
                self._queue_size -= 1
            raise

    @property
    def active_count(self) -> int:
        """当前活跃调用数"""
        return 10 - self._semaphore._value

    @property
    def queue_size(self) -> int:
        return self._queue_size


# 全局 LLM 并发控制器
llm_concurrency = LLMConcurrencyController(max_concurrent=10)


# ─── 超时管理器 ──────────────────────────────────────────────────────

class TimeoutManager:
    """
    超时管理器。

    为不同类型的操作设置不同的超时时间。
    """

    # 默认超时配置（秒）
    DEFAULTS = {
        "llm_chat": 60.0,          # LLM 聊天调用
        "llm_reasoning": 120.0,     # 推理模型调用（更慢）
        "llm_embedding": 30.0,      # Embedding 调用
        "web_search": 30.0,         # 网络搜索
        "db_query": 10.0,           # 数据库查询
        "sse_total": 300.0,         # SSE 流总超时（5分钟）
        "profile_building": 120.0,  # 画像构建
        "job_analysis": 180.0,      # 岗位分析（含背调）
        "resume_generation": 240.0, # 简历生成（包含事实核验与双格式导出）
        "job_matching": 120.0,      # 岗位匹配
    }

    def __init__(self, overrides: dict[str, float] | None = None):
        self._timeouts = {**self.DEFAULTS, **(overrides or {})}

    def get(self, operation: str) -> float:
        """获取操作超时时间"""
        return self._timeouts.get(operation, 60.0)

    async def run_with_timeout(
        self, coro, operation: str = "llm_chat",
        fallback: any = None, error_message: str = "",
    ) -> any:
        """
        带超时的异步执行。

        Usage:
            result = await timeout_mgr.run_with_timeout(
                llm_gateway.chat(...),
                operation="llm_chat",
                fallback="[Timeout]",
            )
        """
        timeout = self.get(operation)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"[Timeout] 操作 '{operation}' 超时 ({timeout}s)"
                + (f": {error_message}" if error_message else "")
            )
            from app.monitoring import metrics
            metrics.record_error(f"TimeoutError:{operation}", "")
            return fallback


# 全局超时管理器
timeout_manager = TimeoutManager()
