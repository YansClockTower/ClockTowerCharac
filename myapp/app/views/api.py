import json
import string
from flask import Blueprint, render_template, request, make_response, send_file, jsonify
from io import BytesIO

from app.models.database import (
    get_character_db,
    get_edition_db
)
from app.models.export_edition_json import generate_edition_json

api_bp = Blueprint("api", __name__)

@api_bp.route('/api/character_info', methods=['POST'])
def character_info():
    names = request.json.get('names', [])
    found = {}
    not_found = []

    conn = get_character_db()
    cursor = conn.cursor()
    
    for cid in names:
        name = cid.strip(string.whitespace + string.punctuation)
        cursor.execute("SELECT * FROM character_info WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            # 假设row是tuple，转成dict
            found[cid] = {
                "id": row["id"],
                "name": row["name"],
                "team": row["team"],
                "ability": row["ability"],
                "image": row["image"],
                "fromEdition": row["fromEdition"]
                # 你需要的其他字段
            }
        else:
            not_found.append(cid)
    return jsonify({"found": found, "not_found": not_found})

@api_bp.route('/api/edition_info', methods=['POST'])
def edition_info():
    name = request.json.get('name', '')

    conn = get_edition_db()
    cursor = conn.cursor()

    name = name.strip(string.whitespace + string.punctuation)
    cursor.execute("SELECT * FROM editions_info WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        # 假设row是tuple，转成dict
        return jsonify({
            "query": "found",
            "id": row["id"],
            "logo": row["logo"],
            "name": row["name"],
            "version": row["version"],
            "author": row["author"],
            "characterList": row["characterList"]
            # 你需要的其他字段
        })
    else:
        return jsonify({"query": "not_found"})

@api_bp.route('/api/edition_json/<id>', methods=['POST'])
def edition_json(id):
    # 读取所选角色 ID
    meta = load_edition_meta(id)

    if not meta: 
        return jsonify({})
    
    statesdict = []
    states_raw = meta.get('states', '')
    if states_raw:
        try:
            data = json.loads(states_raw)
            statesdict = [{
                "stateName": data.get('name', ''),
                "stateDescription": data.get('description', '')
            }]
        except Exception as e:
            print(f"解析states失败: {e}")
            statesdict = []

    char_ids = json.loads(meta.get('characterList', '[]'))
    meta_json = {
        "id": "_meta",
        "name": meta.get('name', 'NewEdition'),
        "author": meta.get('author', 'Unknown'),
        "version": meta.get('version', 'beta'),
        "logo": meta.get('logo', 'https://clocktower.gstonegames.com/images/logo.png'),
        "description": meta.get('description', ''),
        "state": statesdict
    }

    # 生成 JSON 文件名（回退为 NewEdition.json）
    safe_name = meta.get('name', 'NewEdition')
    filename = f"{safe_name}.json"

    json_str = generate_edition_json(
        meta_json,
        char_ids
    )
    return jsonify(json_str)

@api_bp.route('/api/edition_list', methods=['POST'])
def edition_list():
    begin = request.json.get('begin', 0)
    size = request.json.get('size', 100)
    search = request.json.get('search', '')

    conn = get_edition_db()

    cursor = conn.cursor()

    # 构建 SQL
    if search:
        search = f"%{search.strip()}%"
        cursor.execute(
            "SELECT * FROM editions_info WHERE name LIKE ? LIMIT ? OFFSET ?",
            (search, size, begin)
        )
    else:
        cursor.execute(
            "SELECT * FROM editions_info LIMIT ? OFFSET ?",
            (size, begin)
        )

    rows = cursor.fetchall()

    editions = []
    for row in rows:
        editions.append({
            "id": row["id"],
            "logo": row["logo"],
            "name": row["name"],
            "version": row["version"],
            "author": row["author"],
        })

    return jsonify(editions)

