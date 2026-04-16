import datetime
import json
from collections import defaultdict
from io import BytesIO

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for

from app.filter import team_colors, team_mapping
from app.identity import get_current_user
from app.models.database import (
    get_edition_db,
    get_editions_info,
    get_night_order,
    load_character_dict_by_ids,
    load_edition_meta,
)
from app.models.export_edition_json import generate_edition_json

viewedition_bp = Blueprint(
    "editionpdf",
    __name__,
    url_prefix="/script/edition",
    template_folder="templates",
)


def get_statement(meta):
    states = meta.get("states")
    if states:
        try:
            return json.loads(states)
        except Exception as e:
            print(f"[Warning] Failed to parse states for edition id={meta.get('id')}: {e}")
    return None


def group_characters_by_team(char_ids, character_dict):
    teams = defaultdict(list)
    for char_id in char_ids:
        char = character_dict.get(char_id)
        team = char.get("team") or "unknown"
        teams[team].append(char)
    return teams


def get_ordered_teams(char_ids, character_dict):
    grouped = group_characters_by_team(char_ids, character_dict)
    ordered_teams = []
    for key in team_mapping:
        label = team_mapping[key]
        chars = grouped.get(key, [])
        if not chars:
            continue
        color = team_colors.get(key, "#444")
        ordered_teams.append((label, color, chars))
    return ordered_teams


@viewedition_bp.route("/")
def view_all_editions():
    editions = get_editions_info()
    return render_template("list_editions.html", editions=editions)


@viewedition_bp.route("/view/<id>")
def render_edition(id):
    meta = load_edition_meta(id)
    char_ids = json.loads(meta.get("characterList", "[]"))
    character_dict = load_character_dict_by_ids(char_ids)

    state = get_statement(meta)
    first_night = get_night_order(character_dict, "firstNight")
    other_night = get_night_order(character_dict, "otherNight")
    teams_dict = group_characters_by_team(char_ids, character_dict)

    edition_name = meta.get("name", "未知剧本")
    version = meta.get("version", "1.0")
    author = meta.get("author", "匿名")
    logo = meta.get("logo", "https://clocktower.gstonegames.com/images/logo.png")
    minPlayer = meta.get("minPlayer", 7)
    maxPlayer = meta.get("maxPlayer", 5)
    today = datetime.date.today()
    ordered_teams = get_ordered_teams(char_ids, character_dict)

    return render_template(
        "view_edition.html",
        logo=logo,
        author=author,
        edition_name=edition_name,
        version=version,
        minPlayer=minPlayer,
        maxPlayer=maxPlayer,
        state=state,
        character_dict=character_dict,
        first_night=first_night,
        other_night=other_night,
        teams_dict=teams_dict,
        ordered_teams=ordered_teams,
        today=today,
    )


@viewedition_bp.route("/download/<id>", methods=["POST"])
def download_edition_json(id):
    user = get_current_user(update_last_login=False)
    if not user:
        return redirect(url_for("users.user_page"))
    if not user["permission_storyteller"]:
        return "❌ 您没有权限下载json，请联系管理员。"

    meta = load_edition_meta(id)
    statesdict = []
    states_raw = meta.get("states", "")
    if states_raw:
        try:
            data = json.loads(states_raw)
            statesdict = [{"stateName": data.get("name", ""), "stateDescription": data.get("description", "")}]
        except Exception as e:
            print(f"解析states失败: {e}")
            statesdict = []

    char_ids = json.loads(meta.get("characterList", "[]"))
    meta_json = {
        "id": "_meta",
        "name": meta.get("name", "NewEdition"),
        "author": meta.get("author", "Unknown"),
        "version": meta.get("version", "beta"),
        "logo": meta.get("logo", "https://clocktower.gstonegames.com/images/logo.png"),
        "description": meta.get("description", ""),
        "state": statesdict,
    }

    safe_name = meta.get("name", "NewEdition")
    filename = f"{safe_name}.json"
    json_str = generate_edition_json(meta_json, char_ids)
    file_io = BytesIO()
    file_io.write(json_str.encode("utf-8"))
    file_io.seek(0)

    return send_file(file_io, as_attachment=True, download_name=filename, mimetype="application/json")


@viewedition_bp.route("/set_category/<int:id>", methods=["POST"])
def set_category(id):
    user = get_current_user(update_last_login=False)
    if not user:
        return redirect(url_for("users.user_page"))
    if not user["permission_manage_all_editions"]:
        return jsonify({"error": "❌ 您没有权限管理剧本，请联系管理员。"}), 400

    data = request.get_json()
    category = data.get("category")
    if not category:
        return jsonify({"error": "No category provided"}), 400

    db = get_edition_db()
    db.execute("UPDATE editions_info SET category = ? WHERE id = ?", (category, id))
    db.commit()
    return jsonify({"success": True})

