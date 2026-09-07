"""集石抓取冷却：全局限流，降低服务器出口被封风险。"""

from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

# 两次服务器侧抓取的最小间隔（秒）
GSTONE_SCRAPE_COOLDOWN_SECONDS = 20

_lock = threading.Lock()
_last_scrape_monotonic: float = 0.0


def gstone_scrape_cooldown_remaining() -> float:
    """距下次允许抓取还剩多少秒；0 表示可立即抓取。"""
    with _lock:
        elapsed = time.monotonic() - _last_scrape_monotonic
        left = GSTONE_SCRAPE_COOLDOWN_SECONDS - elapsed
        return max(0.0, left)


def try_acquire_gstone_scrape_slot() -> Tuple[bool, float]:
    """尝试占用一次抓取名额。

    Returns:
        (ok, remaining_seconds)：ok 为 False 时 remaining 为还需等待的秒数。
    """
    global _last_scrape_monotonic
    with _lock:
        now = time.monotonic()
        elapsed = now - _last_scrape_monotonic
        if _last_scrape_monotonic > 0 and elapsed < GSTONE_SCRAPE_COOLDOWN_SECONDS:
            return False, GSTONE_SCRAPE_COOLDOWN_SECONDS - elapsed
        _last_scrape_monotonic = now
        return True, 0.0


def release_gstone_scrape_slot_on_failure() -> None:
    """抓取失败时回退时间戳，避免无效请求也占满冷却（保留短惩罚）。"""
    global _last_scrape_monotonic
    with _lock:
        # 失败后仍保留一小段冷却，防止连打坏链
        _last_scrape_monotonic = time.monotonic() - (GSTONE_SCRAPE_COOLDOWN_SECONDS - 10)
        if _last_scrape_monotonic < 0:
            _last_scrape_monotonic = 0.0
