from datetime import datetime
import json
import os
import shutil
import sqlite3
from flask import current_app

# 使用相对路径构造绝对路径

DB_PATH = ''

def db_init():
    global DB_PATH  # 声明要修改的是全局变量
    if DB_PATH == '':
        config = ''
        # 1. Open the config file
        with open('./config.txt', 'r', encoding='utf-8') as config_file:
            # 2. Read the entire file content and parse it as JSON
            config = json.load(config_file)

        # 3. Get the database path from the config
        DB_PATH = config['database_path_dev']
        print("DB_PATH:" + DB_PATH)

def db_backup():
    db_init()
    global DB_PATH  # 声明要修改的是全局变量
    shutil.copy2(DB_PATH+"/edition_latest.sqlite", f'{DB_PATH}/history/{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}_edition.sqlite')
    shutil.copy2(DB_PATH+"/character_latest.sqlite", f'{DB_PATH}/history/{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}_character.sqlite')
    
def get_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def get_character_db():
    db_init()
    global DB_PATH  # 声明要修改的是全局变量
    CHARACTER_DB = DB_PATH+"/character_latest.sqlite"
    return get_db(CHARACTER_DB)

def get_edition_db():
    db_init()
    global DB_PATH  # 声明要修改的是全局变量
    EDITION_DB = DB_PATH+"/edition_latest.sqlite"
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