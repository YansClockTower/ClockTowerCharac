from datetime import datetime
import time
from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)
CHARACTER_PATH = "../database/character_latest.sqlite"
EDITION_PATH = "../database/edition_latest.sqlite"

def get_character_db():
    conn = sqlite3.connect(CHARACTER_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_edition_db():
    conn = sqlite3.connect(EDITION_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_editions_info():
    conn = get_edition_db()
    cursor = conn.execute("SELECT id, name FROM editions_info")
    editions = {row["id"]: row["name"] for row in cursor.fetchall()}
    conn.close()
    return editions

@app.template_filter('datetime')
def format_timestamp(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return '无效时间'


@app.route('/')
def index():
    team_filter = request.args.get('team', '')
    edition_filter = request.args.get('fromEdition', type=int)
    search_query = request.args.get('q', '')

    conn = get_character_db()
    query = 'SELECT id, name, team, fromEdition, image FROM character_info WHERE 1=1'
    params = []

    if team_filter:
        query += ' AND team = ?'
        params.append(team_filter)

    if edition_filter:
        query += ' AND fromEdition = ?'
        params.append(edition_filter)

    if search_query:
        query += ' AND name LIKE ?'
        params.append(f'%{search_query}%')

    characters = conn.execute(query, params).fetchall()
    teams = conn.execute('SELECT DISTINCT team FROM character_info WHERE team != ""').fetchall()
    conn.close()

    # 获取 edition 列表
    editions_info = get_editions_info()

    return render_template(
        'index.html',
        characters=characters,
        teams=teams,
        editions_info=editions_info,
        current_team=team_filter,
        current_edition=edition_filter,
        current_query=search_query
    )


@app.route('/edit/<int:char_id>')
def edit(char_id):
    conn = get_character_db()
    character = conn.execute('SELECT * FROM character_info WHERE id = ?', (char_id,)).fetchone()
    almanac = conn.execute('SELECT * FROM character_almanac WHERE id = ?', (char_id,)).fetchone()
    conn.close()
    return render_template('edit.html', character=character, almanac=almanac)

@app.route('/edit/info/<int:char_id>', methods=['POST'])
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
    return redirect(url_for('edit', char_id=char_id))

@app.route('/edit/almanac/<int:char_id>', methods=['POST'])
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
    return redirect(url_for('edit', char_id=char_id))

@app.route('/view/<int:char_id>')
def view(char_id):
    conn = get_character_db()
    character = conn.execute("SELECT * FROM character_info WHERE id = ?", (char_id,)).fetchone()
    almanac = conn.execute("SELECT * FROM character_almanac WHERE id = ?", (char_id,)).fetchone()
    conn.close()

    return render_template("view.html", character=character, almanac=almanac)

if __name__ == '__main__':
    app.run(debug=True)
