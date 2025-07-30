import json
import string
from flask import Blueprint, render_template, request, make_response, send_file, jsonify
from io import BytesIO

from app.models.database import (
    db_backup,
    get_character_db,
    get_edition_db,
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
            edb.commit()
            edb.close()
            cdb.commit()
            cdb.close()
            
            return """
            <h2>✅ 导入成功</h2>
            <p>剧本数据已成功导入库。</p>
            <a href="/" style="display:inline-block; margin-top:15px; padding:8px 16px; background-color:#4CAF50; color:white; text-decoration:none; border-radius:4px;">
                返回首页
            </a>
            """
        except Exception as e:
            return f"❌ 导入失败: {e}"
    else:
        return render_template('import.html')

