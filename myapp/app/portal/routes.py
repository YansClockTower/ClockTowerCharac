import csv
from pathlib import Path

from flask import Blueprint, render_template

from app.identity import get_current_user

portal_bp = Blueprint("portal", __name__, template_folder="templates")

CONTACT_ZONES_CSV = Path(__file__).with_name("contact_zones.csv")


def load_contact_zones():
    """读取 contact_zones.csv。列名：负责专区、负责人、负责人微信号。"""
    if not CONTACT_ZONES_CSV.is_file():
        return []
    rows = []
    with CONTACT_ZONES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            zone = _csv_cell(row, "负责专区", "专区")
            if not zone:
                continue
            rows.append({
                "zone": zone,
                "nickname": _csv_cell(row, "负责人", "负责人昵称"),
                "wechat": _csv_cell(row, "负责人微信号", "微信号"),
            })
    return rows


def _csv_cell(row, *keys):
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


@portal_bp.route("/")
def index():
    user = get_current_user(update_last_login=False)
    if user:
        username = user["name"]
        userid = user["id"]
        show_join_recruit_group = False
    else:
        username = "游客"
        userid = "0"
        show_join_recruit_group = True

    return render_template(
        "index.html",
        username=username,
        userid=userid,
        show_join_recruit_group=show_join_recruit_group,
        contact_zones=load_contact_zones(),
    )

