import sqlite3
from urllib.error import HTTPError, URLError

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for

from app.identity import get_current_user, login_required_template, token_required
from app.identity.permissions import CONTACT_INFO_COLUMN, EMAIL_COLUMN, user_is_admin
from app.subsystems.boardgames import api as boardgames_api
from app.subsystems.boardgames import gstone_parse as gp
from app.subsystems.boardgames.gstone_cooldown import (
    GSTONE_SCRAPE_COOLDOWN_SECONDS,
    release_gstone_scrape_slot_on_failure,
    try_acquire_gstone_scrape_slot,
)
from app.user.email_codes import find_user_by_username, user_email_verified

boardgames_bp = Blueprint(
    "boardgames",
    __name__,
    url_prefix="/boardgames",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


def _template_user_name():
    user = get_current_user(update_last_login=False)
    return user["name"] if user else None


def _can_edit_game(user, game) -> bool:
    """管理员或桌游所有者可编辑。"""
    if not user or not game:
        return False
    if user_is_admin(user):
        return True
    owner = (game.get("owner") or "").strip()
    return bool(owner) and owner == (user.get("name") or "").strip()


def _owner_contact_for_borrow(game) -> dict:
    """按所有者用户名查找联系方式，供临时借用弹窗展示。"""
    owner_name = (game.get("owner") or "").strip()
    result = {
        "owner_name": owner_name or "（未填写）",
        "owner_found": False,
        "contact_info": "",
        "email": "",
        "email_verified": False,
        "has_contact": False,
    }
    if not owner_name:
        return result
    row = find_user_by_username(owner_name)
    if not row:
        return result
    result["owner_found"] = True
    contact = ""
    try:
        contact = (row[CONTACT_INFO_COLUMN] or "").strip()
    except Exception:
        contact = ""
    if contact in ("", "保密"):
        contact = ""
    email = ""
    try:
        email = (row[EMAIL_COLUMN] or "").strip()
    except Exception:
        email = ""
    verified = user_email_verified(row)
    # 未验证邮箱也展示，但标注；空则不展示
    result["contact_info"] = contact
    result["email"] = email if email else ""
    result["email_verified"] = bool(verified)
    result["has_contact"] = bool(contact or email)
    return result


def _optional_int(form, key):
    raw = (form.get(key) or "").strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _optional_str(form, key):
    v = form.get(key)
    if v is None:
        return None
    s = v.strip()
    return s if s else None


def _game_form_payload(form):
    return {
        "board_game_name": (form.get("board_game_name") or "").strip(),
        "game_type": _optional_str(form, "game_type"),
        "min_players": _optional_int(form, "min_players"),
        "max_players": _optional_int(form, "max_players"),
        "recommended_players": _optional_int(form, "recommended_players"),
        "playing_time": _optional_int(form, "playing_time"),
        "description": _optional_str(form, "description"),
        "image_path": _optional_str(form, "image_path"),
        "owner": (form.get("owner") or "").strip(),
        "current_holder": _optional_str(form, "current_holder"),
        "current_storage_location": _optional_str(form, "current_storage_location"),
    }


def _game_to_form_data(game):
    return {
        "board_game_name": game.get("board_game_name") or "",
        "game_type": game.get("game_type") or "",
        "min_players": "" if game.get("min_players") is None else game.get("min_players"),
        "max_players": "" if game.get("max_players") is None else game.get("max_players"),
        "recommended_players": (
            "" if game.get("recommended_players") is None else game.get("recommended_players")
        ),
        "playing_time": "" if game.get("playing_time") is None else game.get("playing_time"),
        "description": game.get("description") or "",
        "image_path": game.get("image_path") or "",
        "owner": game.get("owner") or "",
        "current_holder": game.get("current_holder") or "",
        "current_storage_location": game.get("current_storage_location") or "",
    }


@boardgames_bp.route("/api/gstone_fetch", methods=("POST",))
@token_required
def gstone_fetch(current_user):
    """服务端抓取集石详情页并映射为登记表单字段（全局限流）。"""
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or request.form.get("url") or "").strip()
    if not url:
        return jsonify({"status": "failed", "reason": "请填写集石桌游详情页网址"}), 400
    if not gp.is_allowed_gstone_url(url):
        return jsonify(
            {
                "status": "failed",
                "reason": "仅支持 https://www.gstonegames.com/game/info-数字.html 形式的详情页",
            }
        ), 400

    ok, wait = try_acquire_gstone_scrape_slot()
    if not ok:
        secs = max(1, int(wait + 0.999))
        return jsonify(
            {
                "status": "failed",
                "reason": f"服务器抓取冷却中，请约 {secs} 秒后再试（全局限流，防集石封禁）",
                "cooldown_remaining": secs,
                "cooldown_seconds": GSTONE_SCRAPE_COOLDOWN_SECONDS,
            }
        ), 429

    try:
        html = gp.fetch_gstone_html(url)
        if gp.is_gstone_challenge_page(html):
            release_gstone_scrape_slot_on_failure()
            return jsonify(
                {
                    "status": "failed",
                    "reason": "集石返回了验证页，服务端未能获取详情。可改用本机脚本导出 JSON 后粘贴识别。",
                }
            ), 502
        info = gp.extract_gstone_game_info(html, url)
        if not info.name:
            release_gstone_scrape_slot_on_failure()
            return jsonify({"status": "failed", "reason": "未能解析桌游名称，页面结构可能已变更"}), 502
        fields = gp.gstone_info_to_register_fields(info)
        return jsonify(
            {
                "status": "success",
                "fields": fields,
                "raw": info.as_dict(),
                "cooldown_seconds": GSTONE_SCRAPE_COOLDOWN_SECONDS,
            }
        )
    except HTTPError as exc:
        release_gstone_scrape_slot_on_failure()
        current_app.logger.warning("gstone_fetch HTTP %s: %s", exc.code, url)
        return jsonify({"status": "failed", "reason": f"集石 HTTP 错误：{exc.code}"}), 502
    except URLError as exc:
        release_gstone_scrape_slot_on_failure()
        current_app.logger.warning("gstone_fetch network: %s", exc.reason)
        return jsonify({"status": "failed", "reason": f"网络错误：{exc.reason}"}), 502
    except Exception:
        release_gstone_scrape_slot_on_failure()
        current_app.logger.exception("gstone_fetch failed")
        return jsonify({"status": "failed", "reason": "抓取或解析失败，请稍后重试"}), 500


@boardgames_bp.route("/")
@boardgames_bp.route("/browse")
def browse():
    games = boardgames_api.list_browse_rows()
    return render_template(
        "board_games/browse.html",
        games=games,
        current_user=_template_user_name(),
    )


@boardgames_bp.route("/register", methods=("GET", "POST"))
@login_required_template
def register(current_user):
    if request.method == "POST":
        payload = _game_form_payload(request.form)
        if not payload["board_game_name"] or not payload["owner"]:
            flash("桌游名称与所有者为必填项。", "error")
            return render_template(
                "board_games/register.html",
                current_user=current_user["name"],
                form_data=request.form.to_dict(flat=True),
            )
        try:
            new_id = boardgames_api.create_registered_game(**payload)
        except sqlite3.Error:
            current_app.logger.exception("boardgames register insert failed")
            flash("登记失败，请稍后重试。", "error")
            return render_template(
                "board_games/register.html",
                current_user=current_user["name"],
                form_data=request.form.to_dict(flat=True),
            )
        flash("登记成功。", "success")
        return redirect(url_for("boardgames.game_detail", game_id=new_id))

    return render_template(
        "board_games/register.html",
        current_user=current_user["name"],
        form_data={"owner": current_user["name"]},
    )


@boardgames_bp.route("/<int:game_id>")
def game_detail(game_id):
    game = boardgames_api.get_game_by_id(game_id)
    if game is None:
        abort(404)
    user = get_current_user(update_last_login=False)
    return render_template(
        "board_games/detail.html",
        game=game,
        current_user=user["name"] if user else None,
        can_edit=_can_edit_game(user, game),
        owner_contact=_owner_contact_for_borrow(game),
    )


@boardgames_bp.route("/<int:game_id>/edit", methods=("GET", "POST"))
@login_required_template
def game_edit(current_user, game_id):
    game = boardgames_api.get_game_by_id(game_id)
    if game is None:
        abort(404)
    if not _can_edit_game(current_user, game):
        flash("仅管理员或桌游所有者可编辑信息。", "error")
        return redirect(url_for("boardgames.game_detail", game_id=game_id))

    if request.method == "POST":
        payload = _game_form_payload(request.form)
        if not payload["board_game_name"] or not payload["owner"]:
            flash("桌游名称与所有者为必填项。", "error")
            return render_template(
                "board_games/edit.html",
                current_user=current_user["name"],
                game=game,
                form_data=request.form.to_dict(flat=True),
            )
        try:
            ok = boardgames_api.update_registered_game(game_id, **payload)
        except sqlite3.Error:
            current_app.logger.exception("boardgames update failed")
            flash("保存失败，请稍后重试。", "error")
            return render_template(
                "board_games/edit.html",
                current_user=current_user["name"],
                game=game,
                form_data=request.form.to_dict(flat=True),
            )
        if not ok:
            flash("保存失败：记录不存在。", "error")
            return redirect(url_for("boardgames.browse"))
        flash("桌游信息已更新。", "success")
        return redirect(url_for("boardgames.game_detail", game_id=game_id))

    return render_template(
        "board_games/edit.html",
        current_user=current_user["name"],
        game=game,
        form_data=_game_to_form_data(game),
    )
