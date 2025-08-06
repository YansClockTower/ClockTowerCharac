from datetime import datetime

team_mapping = {
        'townsfolk': '镇民',
        'outsider': '外来者',
        'minion': '爪牙',
        'demon': '恶魔',
        'fabled': '传奇角色',
        'traveler': '旅行者',
        'jinx': '相克规则'

    }

def format_timestamp(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return '无效时间'

def team_label_filter(team):
    
    return team_mapping.get(team, team)
