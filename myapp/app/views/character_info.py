import time
from flask import Blueprint, render_template, request, redirect, url_for
from app.models.database import get_character_db, get_editions_info, get_filtered_characters

character_bp = Blueprint("character", __name__)

@character_bp.route('/view')
def character_list():
        team_filter = request.args.get('team', '')
        edition_filter = request.args.get('fromEdition', type=int)
        search_query = request.args.get('q', '')

        characters = get_filtered_characters(team_filter, edition_filter, search_query)

        conn = get_character_db()
        teams = conn.execute('SELECT DISTINCT team FROM character_info WHERE team != ""').fetchall()
        conn.close()

        editions_info = get_editions_info()

        return render_template(
            'list_characters.html',
            characters=characters,
            teams=teams,
            editions_info=editions_info,
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

@character_bp.route('/edit_info/<int:char_id>', methods=['POST'])
def edit_info(char_id):
    form = request.form
    conn = get_character_db()
    conn.execute('''
        UPDATE character_info SET
            name = ?, team = ?, ability = ?, setup = ?, firstNight = ?, otherNight = ?,
            firstNightReminder = ?, otherNightReminder = ?, reminders = ?, remindersGlobal = ?,
            image = ?, tags = ?, fromEdition = ?, lastUpdated = ?
        WHERE id = ?
    ''', (
        form['name'], form['team'], form['ability'], int(form['setup']),
        int(form['firstNight']), int(form['otherNight']),
        form['firstNightReminder'], form['otherNightReminder'],
        form['reminders'], form['remindersGlobal'],
        form['image'], form['tags'], int(form['fromEdition']), int(time.time()), char_id
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('character.edit', char_id=char_id))

@character_bp.route('/edit_almanac/<int:char_id>', methods=['POST'])
def edit_almanac(char_id):
    form = request.form
    conn = get_character_db()

    # 如果已存在，更新，否则插入
    existing = conn.execute('SELECT id FROM character_almanac WHERE id = ?', (char_id,)).fetchone()
    if existing:
        conn.execute('''
            UPDATE character_almanac SET
                designer = ?, drawer = ?, overview = ?, examples = ?, howtorun = ?, tips = ?,
                lastUpdated = ?
            WHERE id = ?
        ''', (
            form['designer'], form['drawer'], form['overview'],
            form['examples'], form['howtorun'], form['tips'],
            int(time.time()), char_id
        ))
    else:
        conn.execute('''
            INSERT INTO character_almanac (
                id, designer, drawer, overview, examples, howtorun, tips, fromEdition, lastUpdated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            char_id, form['designer'], form['drawer'], form['overview'],
            form['examples'], form['howtorun'], form['tips'],
            int(form['fromEdition']), int(time.time())
        ))

    conn.commit()
    conn.close()
    return redirect(url_for('character.edit', char_id=char_id))


