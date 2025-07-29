from flask import Blueprint, render_template, request, redirect, url_for
from app.models.db import get_character_db, get_edition_db

character_bp = Blueprint("character", __name__)

@character_bp.route("/")
def index():
    team_filter = request.args.get("team", "")
    search_query = request.args.get("q", "")
    edition_filter = request.args.get("fromEdition", type=int)

    conn = get_character_db()
    query = "SELECT * FROM character_info WHERE 1=1"
    params = []

    if team_filter:
        query += " AND team = ?"
        params.append(team_filter)
    if edition_filter:
        query += " AND fromEdition = ?"
        params.append(edition_filter)
    if search_query:
        query += " AND name LIKE ?"
        params.append(f"%{search_query}%")

    characters = conn.execute(query, params).fetchall()
    teams = conn.execute("SELECT DISTINCT team FROM character_info").fetchall()
    conn.close()

    # 获取 edition 名称映射
    editions = get_edition_db().execute("SELECT id, name FROM editions_info").fetchall()
    editions_info = {row["id"]: row["name"] for row in editions}

    return render_template("index.html", characters=characters, teams=teams,
                           editions_info=editions_info,
                           current_team=team_filter,
                           current_edition=edition_filter,
                           current_query=search_query)

@character_bp.route("/edit/<int:char_id>")
def edit(char_id):
    conn = get_character_db()
    character = conn.execute("SELECT * FROM character_info WHERE id = ?", (char_id,)).fetchone()
    almanac = conn.execute("SELECT * FROM character_almanac WHERE id = ?", (char_id,)).fetchone()
    conn.close()
    return render_template("edit.html", character=character, almanac=almanac)

@character_bp.route("/view/<int:char_id>")
def view(char_id):
    conn = get_character_db()
    character = conn.execute("SELECT * FROM character_info WHERE id = ?", (char_id,)).fetchone()
    almanac = conn.execute("SELECT * FROM character_almanac WHERE id = ?", (char_id,)).fetchone()
    conn.close()
    return render_template("view.html", character=character, almanac=almanac)

@character_bp.route("/edit/<int:char_id>", methods=["POST"])
def edit_info(char_id):
    # 接收 POST 请求并写入 character_info 表
    # ...
    return redirect(url_for("character.edit", char_id=char_id))

@character_bp.route("/edit_almanac/<int:char_id>", methods=["POST"])
def edit_almanac(char_id):
    # 接收 POST 请求并写入 character_almanac 表
    # ...
    return redirect(url_for("character.edit", char_id=char_id))
