from collections import defaultdict
import datetime
import json
import string
from flask import Blueprint, render_template, request, make_response, send_file, jsonify
from io import BytesIO

from app.models.database import (
    db_backup,
    get_all_edition_from_released_characters,
    get_character_db,
    get_edition_db,
    get_filtered_characters,
    get_all_teams,
    get_editions_info,
    get_night_order,
    load_character_dict_by_ids,
    load_edition_meta
)
from app.models.export_edition_json import generate_edition_json
from app.filter import team_mapping, team_colors

buildedition_bp = Blueprint("edition", __name__)

@buildedition_bp.route('/select', methods=['GET'])
def select_characters():
    # 获取筛选参数
    team = request.args.get('team', '')
    from_edition = request.args.get('fromEdition', type=int)
    query = request.args.get('q', '')

    # 查询角色信息
    characters = get_filtered_characters(team, from_edition, query)

    # 获取筛选器数据
    teams = get_all_teams()
    editions_info = get_editions_info()

    selected_ids_str = request.args.get('selected_ids', '')
    selected_ids = selected_ids_str.split(',') if selected_ids_str else []

    # 保留格式化为整数 ID，避免非法注入
    selected_ids = [int(i) for i in selected_ids if i.isdigit()]

    # 查出这些 ID 对应的角色（用于右边已选展示）
    selected_characters = []
    if selected_ids:
        conn = get_character_db()
        q = f"SELECT id, name, team, image, ability FROM character_info WHERE id IN ({','.join(['?']*len(selected_ids))})"
        selected_characters = [dict(row) for row in conn.execute(q, selected_ids).fetchall()]
        conn.close()

    from app.filter import team_mapping

    return render_template(
        'select.html',
        characters=characters,
        teams=teams,
        filter_editions=get_all_edition_from_released_characters(),
        current_team=team,
        current_edition=from_edition,
        current_query=query,
        selected_characters=selected_characters,
        selected_ids=selected_ids_str,
        team_mapping=team_mapping
    )

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

@buildedition_bp.route('/submit_selection', methods=['POST'])
def submit_selection():
    # 读取所选角色 ID
    ids_str = request.form.get('selectedIds', '')
    selected_ids = ids_str.split(',') if ids_str else []

    # 读取其他剧本信息
    edition_name = request.form.get('editionName', '').strip()
    edition_author = request.form.get('editionAuthor', '').strip()
    edition_version = request.form.get('editionVersion', '').strip()
    edition_statement = request.form.get('editionStatements', '').strip()

    action = request.form.get('action', '').strip()

    json_str = generate_edition_json(
        {
            "name": edition_name,
            "author": edition_author,
            "version": edition_version,
            "logo": 'https://clocktower.gstonegames.com/images/logo.png',
            "state": [
                {
                "stateName": "私货商人",
                "stateDescription": edition_statement
                }
            ]
        },
        selected_ids
    )
    
    logo = 'https://clocktower.gstonegames.com/images/logo.png'

    if(action == 'json'):
        # 生成 JSON 文件名（回退为 NewEdition.json）
        safe_name = edition_name if edition_name else 'NewEdition'
        filename = f"{safe_name}.json"

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
    if(action == 'preview'):

            # 一次性加载全部角色信息
            character_dict = load_character_dict_by_ids(selected_ids)

            # 解析声明与夜晚顺序
            first_night = get_night_order(character_dict, 'firstNight')
            other_night = get_night_order(character_dict, 'otherNight')

            teams_dict = group_characters_by_team(character_dict)
            ordered_teams = get_ordered_teams(character_dict)
            full_state = ''
            if(edition_statement):
                full_state = {
                    "name": "私货商人",
                    "description": edition_statement
                }
            return render_template("view_edition.html",
                           logo=logo,
                           author=edition_author,
                           edition_name=edition_name,
                           version='beta',
                           minPlayer=7,
                           maxPlayer=15,
                           state=full_state,
                           character_dict=character_dict,
                           first_night=first_night,
                           other_night=other_night,
                           teams_dict=teams_dict,
                           ordered_teams=ordered_teams,
                           today=datetime.date.today())

@buildedition_bp.route('/import', methods=['GET', 'POST'])
def import_json():
    if request.method == 'POST':
        json_data_str = request.form.get('json_data', '')
        from app.models.fetch_json import import_from_json
        try:
            data = json.loads(json_data_str)
            db_backup()
            edb = get_edition_db()
            cdb = get_character_db()
            import_from_json(data, edb, cdb)
            print("aaa")
            edb.commit()
            edb.close()
            cdb.commit()
            cdb.close()
            
            return """
            <h2>✅ 导入成功</h2>
            <p>剧本数据已成功导入库。</p>
            <a href="/import" style="display:inline-block; margin-top:15px; padding:8px 16px; background-color:#4CAF50; color:white; text-decoration:none; border-radius:4px;">
                确认
            </a>
            """
        except Exception as e:
            return f"❌ 导入失败: {e}"
    else:
        return render_template('import.html')

