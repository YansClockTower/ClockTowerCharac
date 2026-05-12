#!/usr/bin/env python3
"""
从集石 Gstone 桌游详情页（/game/info-<id>.html）抓取固定区块中的元数据。

实现逻辑见 app.subsystems.boardgames.gstone_parse（本脚本为 CLI 入口）。

用法：
  python3 scripts/gstone_game_scrape.py
  python3 scripts/gstone_game_scrape.py "https://www.gstonegames.com/game/info-45174.html"
  python3 scripts/gstone_game_scrape.py --html-file scripts/fixtures/gstone_game_info_45174_sample.html

说明：部分网络环境下站点会返回「集石验证」拦截页（无 details-title 区块）。
此时请用浏览器打开目标页、另存为完整 HTML 后使用 --html-file；或在能返回完整页的环境运行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.subsystems.boardgames import gstone_parse as gp

DEFAULT_URL = "https://www.gstonegames.com/game/info-45174.html"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="抓取集石桌游详情页固定字段")
    p.add_argument("url", nargs="?", default=DEFAULT_URL, help="游戏详情页完整 URL")
    p.add_argument(
        "--html-file",
        metavar="PATH",
        help="从本地已保存的完整 HTML 解析（绕过验证页或用于离线）",
    )
    p.add_argument("--json", action="store_true", help="以 JSON 打印")
    args = p.parse_args(argv)

    try:
        if args.html_file:
            html = gp.load_html_file(args.html_file)
            info = gp.extract_gstone_game_info(html, page_url=f"file:{args.html_file}")
        else:
            html = gp.fetch_gstone_html(args.url)
            if gp.is_gstone_challenge_page(html):
                print(
                    "当前获取到「集石验证」页，未包含桌游详情。请使用浏览器保存完整 HTML 后加 "
                    "`--html-file`，或更换网络/环境后重试。",
                    file=sys.stderr,
                )
                return 2
            info = gp.extract_gstone_game_info(html, args.url)
    except HTTPError as e:
        print(f"HTTP 错误: {e.code} {e.reason}", file=sys.stderr)
        return 1
    except URLError as e:
        print(f"网络错误: {e.reason}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"读取文件失败: {e}", file=sys.stderr)
        return 1

    if not info.name and args.html_file is None and not gp.is_gstone_challenge_page(html):
        print("未能解析名称，页面结构可能已变更。", file=sys.stderr)

    if args.json:
        print(json.dumps(info.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(info.as_dict(), ensure_ascii=False, indent=2))

    # print("URL:", info.url)
    # print("名称:", info.name)
    # print("类型/标签行:", info.game_type_line)
    # print("封面:", info.image_url)
    # print("支持人数(含推荐位):", info.player_support_text or "(未解析)")
    # print("推荐人数:", info.player_recommend_text or "(无)")
    # print("人均时长:", info.duration_per_player)
    # print("简介:\n", info.description)
    # return 0


if __name__ == "__main__":
    raise SystemExit(main())
