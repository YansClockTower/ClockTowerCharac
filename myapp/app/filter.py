from datetime import datetime

from app.models.database import get_edition_db

team_mapping = {
        'townsfolk': '镇民',
        'outsider': '外来者',
        'minion': '爪牙',
        'demon': '恶魔',
        'fabled': '传奇角色',
        'traveler': '旅行者',
        'jinx': '相克规则'

    }

team_colors = {
        "traveler": '#1f1f1f',
        "townsfolk": '#2d7ccd',
        "outsider": "#32abe4",
        "minion": "#cc2625",
        "demon": "#a41e1e",
        "fabled": '#ffc600',
        "jinx": '#1f1f1f'
}

def format_timestamp(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return '无效时间'

def team_label_filter(team):
    return team_mapping.get(team, team)

def team_color_filter(team):
    return team_colors.get(team, '#1f1f1f')

edition_cache = {}

def edition_name_filter(edition_id):
    if edition_id in edition_cache:
        return edition_cache[edition_id]
    
    conn = get_edition_db()
    cursor = conn.execute('SELECT name FROM editions_info WHERE id = ?', (edition_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        edition_name = row[0]
    else:
        edition_name = f'未知剧本({edition_id})'
    
    edition_cache[edition_id] = edition_name
    return edition_name