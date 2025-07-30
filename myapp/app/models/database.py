import os
import sqlite3

# 当前脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 使用相对路径构造绝对路径
CHARACTER_DB = os.path.join(BASE_DIR, 'database', 'character_latest.sqlite')
EDITION_DB   = os.path.join(BASE_DIR, 'database', 'edition_latest.sqlite')

def get_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def get_character_db():
    return get_db(CHARACTER_DB)

def get_edition_db():
    return get_db(EDITION_DB)

def get_editions_info():
    conn = get_edition_db()
    cursor = conn.execute("SELECT id, name FROM editions_info")
    editions = {row["id"]: row["name"] for row in cursor.fetchall()}
    conn.close()
    return editions

def get_filtered_characters(team_filter='', edition_filter=None, search_query=''):
    conn = get_character_db()
    query = 'SELECT id, name, team, fromEdition, image, ability FROM character_info WHERE 1=1'
    params = []

    if team_filter:
        query += ' AND team = ?'
        params.append(team_filter)

    if edition_filter is not None:
        query += ' AND fromEdition = ?'
        params.append(edition_filter)

    if search_query:
        query += ' AND name LIKE ?'
        params.append(f'%{search_query}%')

    characters = conn.execute(query, params).fetchall()
    characters = [dict(row) for row in characters]
    conn.close()
    return characters

def get_all_teams():
    conn = get_character_db()
    teams = conn.execute('SELECT DISTINCT team FROM character_info WHERE team != ""').fetchall()
    conn.close()
    return teams