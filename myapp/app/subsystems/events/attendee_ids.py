"""为活动列表中的 attendee_notes 补充 user_info.id，便于链到用户资料页。"""

from app.models.database import get_user_db


def enrich_events_attendees_user_ids(events):
    """就地写入每条 attendance 的 user_id（无账号则 user_id 为 None）。"""
    names = set()
    for ev in events or []:
        for a in ev.get("attendee_notes") or []:
            n = a.get("player")
            if n:
                names.add(n)
    if not names:
        for ev in events or []:
            for a in ev.get("attendee_notes") or []:
                a["user_id"] = None
        return

    user_db = get_user_db()
    placeholders = ",".join("?" * len(names))
    rows = user_db.execute(
        f"SELECT id, name FROM user_info WHERE name IN ({placeholders})",
        tuple(names),
    ).fetchall()
    user_db.close()
    lookup = {row["name"]: row["id"] for row in rows}
    for ev in events or []:
        for a in ev.get("attendee_notes") or []:
            a["user_id"] = lookup.get(a.get("player"))
