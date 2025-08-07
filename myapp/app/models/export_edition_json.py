import json
from .database import get_character_db  # 假设你已有连接数据库的封装

def generate_edition_json(edition_meta, selected_ids):
    """
    根据表单和所选角色 ID 生成剧本 JSON。
    :param edition_name: 剧本标题
    :param edition_author: 剧本作者
    :param edition_version: 剧本版本
    :param selected_ids: List[int] 所选角色 ID 列表
    :return: JSON 字符串
    """
    result = []

    # 添加 meta 信息
    meta = edition_meta;
    meta['id'] = "_meta"

    result.append(meta)

    if not selected_ids:
        return json.dumps(result, ensure_ascii=False, indent=2)

    # 查询数据库获取角色信息
    conn = get_character_db()
    placeholder = ','.join(['?'] * len(selected_ids))
    query = f"SELECT * FROM character_info WHERE id IN ({placeholder})"
    rows = conn.execute(query, selected_ids).fetchall()
    characters = [dict(row) for row in rows]
    conn.close()

    for row in characters:
        item = {
            "id": "_"+str(row["id"]),
            "name": row["name"],
            "image": row["image"],
            "team": row["team"],
            "ability": row.get("ability", ""),
        }

        # 可选字段（如果存在就加）
        if row.get("firstNight"):
            item["firstNight"] = row["firstNight"]
        if row.get("firstNightReminder"):
            item["firstNightReminder"] = row["firstNightReminder"]

        if row.get("otherNight"):
            item["otherNight"] = row["otherNight"]
        if row.get("otherNightReminder"):
            item["otherNightReminder"] = row["otherNightReminder"]
        
        if row.get("reminders"):
            # 假设数据库中是 JSON 字符串
            try:
                item["reminders"] = json.loads(row["reminders"])
            except:
                item["reminders"] = [row["reminders"]]

        if row.get("remindersGlobal"):
            # 假设数据库中是 JSON 字符串
            try:
                item["remindersGlobal"] = json.loads(row["remindersGlobal"])
            except:
                item["remindersGlobal"] = [row["remindersGlobal"]]

        result.append(item)

    return json.dumps(result, ensure_ascii=False, indent=2)
