from io import BytesIO
from flask import Blueprint, render_template, send_file
from app.models.database import get_character_db, get_edition_db, get_editions_info
import datetime
import json
from collections import defaultdict
from app.filter import team_mapping, team_colors
from app.models.export_edition_json import generate_edition_json

viewedition_bp = Blueprint("editionpdf", __name__)

# ---- 数据库加载函数 ----

def load_meta(edition_id):
    conn = get_edition_db()
    cursor = conn.execute("SELECT * FROM editions_info WHERE id = ?", (edition_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Edition '{edition_id}' not found")
    return dict(row)

def load_character_dict_by_ids(char_ids):
    if not char_ids:
        return {}

    placeholders = ','.join(['?'] * len(char_ids))
    conn = get_character_db()
    cursor = conn.execute(f'''
        SELECT * FROM character_info
        WHERE id IN ({placeholders})
    ''', char_ids)

    result = {}
    for row in cursor.fetchall():
        char = dict(row)
        result[char['id']] = char  # 以 id 为键
    conn.close()
    return result


def get_statement(meta):
    states = meta.get("states")
    if states:
        try:
            return json.loads(states)
        except Exception as e:
            print(f"[Warning] Failed to parse states for edition id={meta.get('id')}: {e}")
    return None

def get_night_order(character_dict, key):
    # 过滤掉 key 对应值为 None 或 0
    filtered = [char for char in character_dict.values() if char.get(key) not in (None, 0)]
    sorted_chars = sorted(filtered, key=lambda c: c[key])
    return [char['id'] for char in sorted_chars]

def group_characters_by_team(character_dict):
    teams = defaultdict(list)
    for char in character_dict.values():
        team = char.get('team') or 'unknown'
        teams[team].append(char)
    return teams



def get_ordered_teams(character_dict):
    grouped = group_characters_by_team(character_dict)
    ordered_teams = []
    for key in team_mapping:
        label = team_mapping[key]
        chars = grouped.get(key, [])
        if not chars:
            continue  # 跳过空团队
        color = team_colors.get(key, "#444")  # 默认颜色
        ordered_teams.append((label, color, chars))
    return ordered_teams

# ---- 路由函数 ----

@viewedition_bp.route("/viewedition")
def view_all_editions():
    editions = get_editions_info()  # 返回 {id: name}
    return render_template("list_editions.html", editions=editions)

@viewedition_bp.route("/viewedition/<id>")
def render_edition(id):
    meta = load_meta(id)
    char_ids = json.loads(meta.get('characterList', '[]'))

    # 一次性加载全部角色信息
    character_dict = load_character_dict_by_ids(char_ids)

    # 解析声明与夜晚顺序
    state = get_statement(meta)
    first_night = get_night_order(character_dict, 'firstNight')
    other_night = get_night_order(character_dict, 'otherNight')

    teams_dict = group_characters_by_team(character_dict)

    # 获取基本字段
    edition_name = meta.get("name", "未知剧本")
    version = meta.get("version", "1.0")
    author = meta.get("author", "匿名")
    logo = meta.get("logo", 'https://clocktower.gstonegames.com/images/logo.png')
    today = datetime.date.today()

    grouped = group_characters_by_team(character_dict)

    ordered_teams = get_ordered_teams(character_dict)

    return render_template("view_edition.html",
                           logo=logo,
                           author=author,
                           edition_name=edition_name,
                           version=version,
                           state=state,
                           character_dict=character_dict,
                           first_night=first_night,
                           other_night=other_night,
                           teams_dict=teams_dict,
                           ordered_teams=ordered_teams,
                           today=today)

@viewedition_bp.route('/downloadedition/<id>', methods=['POST'])
def download_edition_json(id):
    # 读取所选角色 ID
    meta = load_meta(id)
    char_ids = json.loads(meta.get('characterList', '[]'))
    meta_json = {
        "id": "_meta",
        "name": meta.get('name', 'NewEdition'),
        "author": meta.get('author', 'Unknown'),
        "version": meta.get('version', 'beta'),
        "logo": meta.get('logo', 'https://clocktower.gstonegames.com/images/logo.png'),
        "description": meta.get('description', ''),
        "states": meta.get('states', '')
    }

    # 生成 JSON 文件名（回退为 NewEdition.json）
    safe_name = meta.get('name', 'NewEdition')
    filename = f"{safe_name}.json"

    json_str = generate_edition_json(
        meta_json,
        char_ids
    )
    # 将 JSON 内容写入内存中的 BytesIO 对象
    file_io = BytesIO()
    file_io.write(json_str.encode('utf-8'))
    file_io.seek(0)

    # 返回文件下载响应
    return send_file(
        file_io,
        as_attachment=True,
        download_name=filename,
        mimetype='application/json'
    )