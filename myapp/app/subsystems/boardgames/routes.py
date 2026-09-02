import sqlite3

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from app.identity import get_current_user, login_required_template
from app.identity.permissions import user_is_admin
from app.subsystems.boardgames import api as boardgames_api

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
        can_edit=user_is_admin(user) if user else False,
    )


@boardgames_bp.route("/<int:game_id>/edit", methods=("GET", "POST"))
@login_required_template
def game_edit(current_user, game_id):
    if not user_is_admin(current_user):
        flash("仅管理员可编辑桌游信息。", "error")
        return redirect(url_for("boardgames.game_detail", game_id=game_id))

    game = boardgames_api.get_game_by_id(game_id)
    if game is None:
        abort(404)

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
