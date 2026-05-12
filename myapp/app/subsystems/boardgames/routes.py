import sqlite3

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from app.identity import get_current_user, login_required_template
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
        board_game_name = (request.form.get("board_game_name") or "").strip()
        owner = (request.form.get("owner") or "").strip()
        if not board_game_name or not owner:
            flash("桌游名称与所有者为必填项。", "error")
            return render_template(
                "board_games/register.html",
                current_user=current_user["name"],
                form_data=request.form.to_dict(flat=True),
            )
        try:
            new_id = boardgames_api.create_registered_game(
                board_game_name=board_game_name,
                game_type=_optional_str(request.form, "game_type"),
                min_players=_optional_int(request.form, "min_players"),
                max_players=_optional_int(request.form, "max_players"),
                recommended_players=_optional_int(request.form, "recommended_players"),
                playing_time=_optional_int(request.form, "playing_time"),
                description=_optional_str(request.form, "description"),
                image_path=_optional_str(request.form, "image_path"),
                owner=owner,
                current_holder=owner,
                current_storage_location=_optional_str(request.form, "current_storage_location"),
            )
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
    return render_template(
        "board_games/detail.html",
        game=game,
        current_user=_template_user_name(),
    )
