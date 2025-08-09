import time
from flask import Blueprint, render_template, request, redirect, url_for
from app.models.database import get_all_edition_from_released_characters, get_character_db, get_editions_info, get_filtered_characters

character_bp = Blueprint("character", __name__)

@character_bp.route('/view')
def character_list():
        team_filter = request.args.get('team', '')
        edition_filter = request.args.get('fromEdition', type=int)
        search_query = request.args.get('q', '')

        characters = get_filtered_characters(team_filter, edition_filter, search_query, True)

        conn = get_character_db()
        teams = conn.execute('SELECT DISTINCT team FROM character_info WHERE team != ""').fetchall()
        conn.close()

        return render_template(
            'list_characters.html',
            characters=characters,
            teams=teams,
            filter_editions=get_all_edition_from_released_characters(),
            current_team=team_filter,
            current_edition=edition_filter,
            current_query=search_query
        )

@character_bp.route("/edit/<int:char_id>")
def edit(char_id):
    conn = get_character_db()
    character = conn.execute("SELECT * FROM character_info WHERE id = ?", (char_id,)).fetchone()
    almanac = conn.execute("SELECT * FROM character_almanac WHERE id = ?", (char_id,)).fetchone()
    conn.close()
    return render_template("edit_character.html", character=character, almanac=almanac)

@character_bp.route("/view/<int:char_id>")
def view(char_id):
    conn = get_character_db()
    character = conn.execute("SELECT * FROM character_info WHERE id = ?", (char_id,)).fetchone()
    almanac = conn.execute("SELECT * FROM character_almanac WHERE id = ?", (char_id,)).fetchone()
    conn.close()
    return render_template("view_character.html", character=character, almanac=almanac)

# @character_bp.route("/edit/<int:char_id>", methods=["POST"])
# def edit_info(char_id):
#     # 接收 POST 请求并写入 character_info 表
#     # ...
#     return redirect(url_for("character.edit", char_id=char_id))

# @character_bp.route("/edit_almanac/<int:char_id>", methods=["POST"])
# def edit_almanac(char_id):
#     # 接收 POST 请求并写入 character_almanac 表
#     # ...
#     return redirect(url_for("character.edit", char_id=char_id))

@character_bp.route('/submit/<int:char_id>', methods=['POST'])
def edit_submit(char_id):
    form = request.form
    conn = get_character_db()

    # 更新 character_info
    conn.execute('''
        UPDATE character_info SET
            name = ?, team = ?, ability = ?, setup = ?, firstNight = ?, otherNight = ?,
            firstNightReminder = ?, otherNightReminder = ?, reminders = ?, remindersGlobal = ?,
            image = ?, tags = ?, fromEdition = ?, released = ?, lastUpdated = ?
        WHERE id = ?
    ''', (
        form['name'], form['team'], form['ability'], int(form['setup']),
        int(form['firstNight']), int(form['otherNight']),
        form['firstNightReminder'], form['otherNightReminder'],
        form['reminders'], form['remindersGlobal'],
        form['image'], form['tags'], int(form['fromEdition']),
        int(form.get('released', 1)),  # released字段
        int(time.time()), char_id
    ))

    # 查询历书是否存在
    existing = conn.execute('SELECT id FROM character_almanac WHERE id = ?', (char_id,)).fetchone()
    if existing:
        conn.execute('''
            UPDATE character_almanac SET
                designer = ?, drawer = ?, overview = ?, examples = ?, howtorun = ?, tips = ?,
                lastUpdated = ?
            WHERE id = ?
        ''', (
            form.get('designer', ''), form.get('drawer', ''), form.get('overview', ''),
            form.get('examples', ''), form.get('howtorun', ''), form.get('tips', ''),
            int(time.time()), char_id
        ))
    else:
        conn.execute('''
            INSERT INTO character_almanac (
                id, designer, drawer, overview, examples, howtorun, tips, fromEdition, lastUpdated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            char_id, form.get('designer', ''), form.get('drawer', ''), form.get('overview', ''),
            form.get('examples', ''), form.get('howtorun', ''), form.get('tips', ''),
            int(form.get('fromEdition', 0)), int(time.time())
        ))

    conn.commit()
    conn.close()
    return redirect(url_for('character.edit', char_id=char_id))
