from flask import Blueprint, render_template, request, make_response, send_file
from io import BytesIO

from app.models.database import (
    get_character_db,
    get_filtered_characters,
    get_all_teams,
    get_editions_info
)
from app.models.export_edition_json import generate_edition_json

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
        editions_info=editions_info,
        current_team=team,
        current_edition=from_edition,
        current_query=query,
        selected_characters=selected_characters,
        selected_ids=selected_ids_str,
        team_mapping=team_mapping
    )


@buildedition_bp.route('/submit_selection', methods=['POST'])
def submit_selection():
    # 读取所选角色 ID
    ids_str = request.form.get('selectedIds', '')
    selected_ids = ids_str.split(',') if ids_str else []

    # 读取其他剧本信息
    edition_name = request.form.get('editionName', '').strip()
    edition_author = request.form.get('editionAuthor', '').strip()
    edition_version = request.form.get('editionVersion', '').strip()

    json_str = generate_edition_json(
        edition_name,
        edition_author,
        edition_version,
        selected_ids
    )
    
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
