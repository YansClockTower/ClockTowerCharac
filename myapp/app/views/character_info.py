from flask import Blueprint, render_template, request, redirect, url_for
from app.models.database import get_character_db, get_editions_info, get_filtered_characters

character_bp = Blueprint("character", __name__)

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
