import json
import sqlite3
import string
import time


def insert_character(character_data, editionId, author, database):
    # 提取字段并处理 reminders
    image = character_data.get("image", "")
    name = character_data.get("name", "").strip(string.whitespace + string.punctuation)
    team = character_data.get("team", "").strip(string.whitespace + string.punctuation)
    ability = character_data.get("ability", "")
    setup = int(character_data.get("setup", False))
    firstNight = character_data.get("firstNight", 0)
    otherNight = character_data.get("otherNight", 0)
    firstNightReminder = character_data.get("firstNightReminder", "")
    otherNightReminder = character_data.get("otherNightReminder", "")
    reminders = json.dumps(character_data.get("reminders", []), ensure_ascii=False)
    remindersGlobal = json.dumps(character_data.get("remindersGlobal", []), ensure_ascii=False)

    # 连接数据库并插入
    conn = database
    cursor = conn.cursor()

    cursor.execute('SELECT id FROM character_info WHERE name = ?', (name,))
    existing = cursor.fetchone()

    if existing:
        print(f"{name} exists with ID {existing[0]}. Skipped.")
        # 已存在，返回已存在的 ID
        return existing[0]
    else:
        cursor.execute('''
            INSERT INTO character_info (
                image, name, team, ability, setup,
                firstNight, otherNight,
                firstNightReminder, otherNightReminder, reminders, remindersGlobal, 
                fromEdition, tags, lastUpdated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            image,
            name,
            team,
            ability,
            setup,
            firstNight,
            otherNight,
            firstNightReminder,
            otherNightReminder,
            reminders,
            remindersGlobal,
            editionId,
            '[]',
            int(time.time())
        ))

        cursor.execute('''
            INSERT INTO character_almanac (
                designer, lastUpdated
            ) VALUES (?,  ?)
        ''', (
            author,
            int(time.time())
        ))

        return cursor.lastrowid


def import_from_json(json_file, edition_base, character_base):

######################################
### save the edition info
###
    editionName = ''
    version = 'beta'
    author = 'unknown'
    logo = ''
    description = ''
    editionId = 0
    for ch in json_file:
        
        if ch['id'] == '_meta':
            editionName = ch['name']
            if 'version' in ch:
                version = ch['version']
            if 'author' in ch:
                author = ch['author']
            if 'logo' in ch:
                logo = ch['logo']
            if 'description' in ch:
                description = ch['description']
            break
    
        # 保存到 editions_info 表
    conn = edition_base
    cursor = conn.cursor()

    # 查询是否已存在同名剧本
    cursor.execute('SELECT id FROM editions_info WHERE name = ?', (editionName,))
    existing = cursor.fetchone()

    if existing:
        # 已存在则执行 UPDATE
        editionId = existing[0]
        cursor.execute('''
            UPDATE editions_info
            SET logo = ?, description = ?, version = ?, author = ?, lastUpdated = ?
            WHERE id = ?
        ''', (
            logo,
            description,
            version,
            author,
            int(time.time()),
            editionId
        ))
    else:
        # 不存在则 INSERT
        cursor.execute('''
            INSERT INTO editions_info (
                logo, name, description, version, author, lastUpdated
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            logo,
            editionName,
            description,
            version,
            author,
            int(time.time())
        ))
        editionId = cursor.lastrowid

######################################
### save the character info
###
    characters = []
    for ch in json_file:
        if ch['id'] != '_meta' and 'jinx' not in ch['team']:
            if 'travel' in ch['team']:
                ch['team'] = 'traveler'
            ids = insert_character(ch, editionId, author, character_base)
            characters.append(ids)
            image_url = ''
            if 'image' in ch:
                image_url = ch['image']
        

    cursor.execute('''
        UPDATE editions_info
        SET characterList = ?
        WHERE id = ?
    ''', (json.dumps(characters, ensure_ascii=False), editionId))

