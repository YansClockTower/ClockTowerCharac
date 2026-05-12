"""集石桌游详情页 HTML 解析（供 CLI 脚本与 Flask API 复用）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class GstoneGameInfo:
    url: str
    name: str
    game_type_line: str
    description: str
    image_url: str
    player_support_text: str
    player_recommend_text: str
    duration_per_player: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "name": self.name,
            "game_type_line": self.game_type_line,
            "description": self.description,
            "image_url": self.image_url,
            "player_support_text": self.player_support_text,
            "player_recommend_text": self.player_recommend_text,
            "duration_per_player": self.duration_per_player,
        }


def fetch_gstone_html(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        charset = "utf-8"
        ct = resp.headers.get_content_charset()
        if ct:
            charset = ct
        return resp.read().decode(charset, errors="replace")


def load_html_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def is_gstone_challenge_page(html: str) -> bool:
    if "<title>集石验证</title>" in html or "<title>集石验证" in html[:2500]:
        return True
    if "集石验证" in html[:4000] and "details-title" not in html:
        return True
    return False


def _strip_tags(html_fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _normalize_image_url(src: str) -> str:
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://www.gstonegames.com" + src
    return src


def _parse_player_lists(player_num_list: dict[str, int]) -> tuple[list[int], list[int]]:
    support_or_both: list[int] = []
    recommend_only: list[int] = []
    for k, v in player_num_list.items():
        try:
            n = int(k)
        except ValueError:
            continue
        if v == 1:
            support_or_both.append(n)
        elif v == 2:
            support_or_both.append(n)
            recommend_only.append(n)
    support_or_both.sort()
    recommend_only.sort()
    return support_or_both, recommend_only


def _format_player_span(nums: list[int]) -> str:
    if not nums:
        return ""
    if len(nums) == 1:
        n = nums[0]
        return f"{n}+" if n >= 14 else str(n)
    parts: list[str] = []
    start = prev = nums[0]
    for x in nums[1:]:
        if x == prev + 1:
            prev = x
            continue
        parts.append(f"{start}–{prev}" if start != prev else str(start))
        start = prev = x
    parts.append(f"{start}–{prev}" if start != prev else str(start))
    return "、".join(parts)


def extract_gstone_game_info(html: str, page_url: str) -> GstoneGameInfo:
    name = ""
    game_type_line = ""
    title_block_m = re.search(
        r'<div class="details-title">(.*?)</div>\s*<div class="infor\b',
        html,
        re.DOTALL,
    )
    if title_block_m:
        block = title_block_m.group(1)
        h2_titles = re.findall(r"<h2><a[^>]*>([^<]*)</a></h2>", block)
        if h2_titles:
            name = h2_titles[-1].strip()
        type_m = re.search(r"</h3>\s*<p>(.*?)</p>", block, re.DOTALL)
        game_type_line = _strip_tags(type_m.group(1)) if type_m else ""

    img_m = re.search(
        r'class="game_logo_preview"[\s\S]*?<img\s+[^>]*src="([^"]+)"',
        html,
        re.I,
    )
    image_url = _normalize_image_url(img_m.group(1)) if img_m else ""

    desc_m = re.search(
        r'<p\s+v-if="\(curtLang==\'sch\'\)">\s*(.*?)\s*</p>\s*<p\s+v-if="\(curtLang==\'eng\'\)"',
        html,
        re.DOTALL | re.I,
    )
    description = _strip_tags(desc_m.group(1)) if desc_m else ""

    duration_m = re.search(r"人均时长：([^<]+)</p>", html)
    duration_per_player = duration_m.group(1).strip() if duration_m else ""

    plist_m = re.search(r"playerNumList:\s*(\{[^}]+\})", html)
    player_support_text = ""
    player_recommend_text = ""
    if plist_m:
        try:
            raw = json.loads(plist_m.group(1))
            plist = {str(k): int(v) for k, v in raw.items()}
            supported, recommended = _parse_player_lists(plist)
            player_support_text = _format_player_span(supported)
            player_recommend_text = _format_player_span(recommended)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return GstoneGameInfo(
        url=page_url,
        name=name,
        game_type_line=game_type_line,
        description=description,
        image_url=image_url,
        player_support_text=player_support_text,
        player_recommend_text=player_recommend_text,
        duration_per_player=duration_per_player,
    )


def scrape_gstone_game_page(url: str) -> GstoneGameInfo:
    html = fetch_gstone_html(url)
    return extract_gstone_game_info(html, url)


def parse_min_max_players(support_text: str) -> tuple[Optional[int], Optional[int]]:
    """从「3–6」「14+」等文案解析最少/最多人数。"""
    t = (support_text or "").strip()
    if not t:
        return None, None
    first = t.split("、")[0].strip()
    m = re.match(r"^(\d+)\s*[–-]\s*(\d+)$", first)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r"^(\d+)\+$", first)
    if m2:
        return int(m2.group(1)), None
    m3 = re.match(r"^(\d+)$", first)
    if m3:
        n = int(m3.group(1))
        return n, n
    return None, None


def parse_playing_time_minutes(duration_per_player: str) -> Optional[int]:
    """从「10分钟/人」等文案取首个整数作为参考时长（分钟）。"""
    m = re.search(r"(\d+)\s*分钟", duration_per_player or "")
    return int(m.group(1)) if m else None


def parse_recommended_players_int(text: Optional[str]) -> Optional[int]:
    """从 player_recommend_text（如「4」「2–3」）解析为单个整数，取文案中数字的最大值。"""
    if not text or not str(text).strip():
        return None
    nums = [int(x) for x in re.findall(r"\d+", str(text))]
    return max(nums) if nums else None


def gstone_info_to_register_fields(info: GstoneGameInfo) -> dict[str, Any]:
    """映射为登记表单字段（不含 owner / current_holder / current_storage_location）。"""
    mn, mx = parse_min_max_players(info.player_support_text)
    playing = parse_playing_time_minutes(info.duration_per_player)
    rec = parse_recommended_players_int(info.player_recommend_text)
    desc = info.description
    if info.duration_per_player and not playing:
        desc = f"{desc}\n\n（集石人均时长：{info.duration_per_player}）".strip()
    return {
        "board_game_name": info.name,
        "game_type": info.game_type_line,
        "min_players": "" if mn is None else str(mn),
        "max_players": "" if mx is None else str(mx),
        "recommended_players": "" if rec is None else str(rec),
        "playing_time": "" if playing is None else str(playing),
        "description": desc,
        "image_path": info.image_url,
    }


# 供脚本与路由复用
GSTONE_GAME_INFO_URL = re.compile(
    r"^https://www\.gstonegames\.com/game/info-\d+(?:-\d+)?\.html(?:\?.*)?$",
    re.I,
)


def is_allowed_gstone_url(url: str) -> bool:
    return bool(url and GSTONE_GAME_INFO_URL.match(url.strip()))
