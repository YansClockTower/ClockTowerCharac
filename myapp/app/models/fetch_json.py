import json
import sqlite3
import string
import time


def insert_character(character_data, editionId, author, database):
    # 提取字段并处理 reminders

    name = character_data.get("name", "").strip(string.whitespace + string.punctuation)
    print("inserting character: ", name)
    image = character_data.get("image", "")
    if len(image[0]) > 5:
        image = image[0]
    team = character_data.get("team", "").strip(string.whitespace + string.punctuation)
    ability = character_data.get("ability", "")
    setup = int(character_data.get("setup", False))
    firstNight = character_data.get("firstNight", 0)
    otherNight = character_data.get("otherNight", 0)
    firstNightReminder = character_data.get("firstNightReminder", "")
    otherNightReminder = character_data.get("otherNightReminder", "")
    reminders = json.dumps(character_data.get("reminders", []), ensure_ascii=False)
    remindersGlobal = json.dumps(character_data.get("remindersGlobal", []), ensure_ascii=False)
    
    cursor = database.cursor()

    # 查询是否存在同名角色，并获取其 id 和 fromEdition
    cursor.execute('SELECT id, fromEdition FROM character_info WHERE name = ?', (name,))
    existing = cursor.fetchone()

    if existing:
        # 如果存在，且 fromEdition 不同，则跳过插入
        if existing[1] != editionId:
            print(f"{name} exists with ID {existing[0]} from edition {existing[1]}. Skipped.")
        else:
            cursor.execute('''
                UPDATE character_info SET
                    image = ?, team = ?, ability = ?, setup = ?,
                    firstNight = ?, otherNight = ?,
                    firstNightReminder = ?, otherNightReminder = ?,
                    reminders = ?, remindersGlobal = ?,
                    lastUpdated = ?
                WHERE id = ?
            ''', (
                image,
                team,
                ability,
                setup,
                firstNight,
                otherNight,
                firstNightReminder,
                otherNightReminder,
                reminders,
                remindersGlobal,
                int(time.time()),
                existing[0]
            ))
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
            ) VALUES (?, ?)
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
    states = ''
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
            if 'state' in ch:
                if len(ch['state']) == 1:
                    states = {
                        "name": ch['state'][0].get('stateName').strip(),
                        "description": ch['state'][0].get('stateDescription').strip()
                        }
                if len(ch['state']) > 1:
                    state_lines = []
                    for item in ch['state']:
                        name = item.get('stateName', '').strip()
                        desc = item.get('stateDescription', '').strip()
                        if name and desc:
                            state_lines.append(f"{name}：{desc}")
                    states = {
                        "name": "私货商人",
                        "description": "\n".join(state_lines)
                        }
            break
    
        # 保存到 editions_info 表
    conn = edition_base
    cursor = conn.cursor()

    # 查询是否已存在同名剧本
    cursor.execute('SELECT id FROM editions_info WHERE name = ?', (editionName,))
    existing = cursor.fetchone()
    print("inserting character bbbb")
    if existing:
        # 已存在则执行 UPDATE
        editionId = existing[0]
        cursor.execute('''
            UPDATE editions_info
            SET logo = ?, description = ?, version = ?, author = ?, lastUpdated = ?, states = ?
            WHERE id = ?
        ''', (
            logo,
            description,
            version,
            author,
            int(time.time()),
            json.dumps(states),
            editionId,
        ))
    else:
        # 不存在则 INSERT
        cursor.execute('''
            INSERT INTO editions_info (
                logo, name, description, version, author, lastUpdated, states
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            logo,
            editionName,
            description,
            version,
            author,
            int(time.time()),
            json.dumps(states)
        ))
        editionId = cursor.lastrowid
    print("inserting aaaa")
######################################
### save the character info
###
    characters = []
    for ch in json_file:
        if ch['id'] != '_meta' and 'jinx' not in ch['team']:
            if 'travel' in ch['team']:
                ch['team'] = 'traveler'
            if 'jinx' in ch['team']:
                ch['team'] = 'jinx'
            ids = insert_character(ch, editionId, author, character_base)
            characters.append(ids)

    cursor.execute('''
        UPDATE editions_info
        SET characterList = ?
        WHERE id = ?
    ''', (json.dumps(characters, ensure_ascii=False), editionId))

