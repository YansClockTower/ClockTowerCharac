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


_BLANK_CONTACTS = {"", "保密", "未填写", "无", "-", "—"}


def enrich_events_inviter_contacts(events):
    """就地写入 inviter_wechat。未填写或「保密」视为没有微信号。"""
    from app.identity.permissions import ensure_user_permission_schema

    names = set()
    for ev in events or []:
        name = (ev.get("inviter") or "").strip()
        if name:
            names.add(name)
    lookup = {}
    if names:
        ensure_user_permission_schema()
        user_db = get_user_db()
        placeholders = ",".join("?" * len(names))
        rows = user_db.execute(
            f"SELECT name, contact_info FROM user_info WHERE name IN ({placeholders})",
            tuple(names),
        ).fetchall()
        user_db.close()
        for row in rows:
            raw = (row["contact_info"] or "").strip()
            lookup[row["name"]] = "" if raw in _BLANK_CONTACTS else raw
    for ev in events or []:
        ev["inviter_wechat"] = lookup.get((ev.get("inviter") or "").strip(), "")
