from flask import Blueprint, render_template

from app.identity import get_current_user
from app.identity.permissions import MEMBER_ORDER_NO_COLUMN
from app.user.membership import user_is_member

portal_bp = Blueprint("portal", __name__, template_folder="templates")


def _row_get(user, key, default=None):
    if user is None:
        return default
    try:
        if key in user.keys():
            val = user[key]
            return default if val is None else val
    except Exception:
        pass
    return default


@portal_bp.route("/")
def index():
    user = get_current_user(update_last_login=False)
    if user:
        username = user["name"]
        userid = user["id"]
        order_no = (_row_get(user, MEMBER_ORDER_NO_COLUMN, "") or "").strip()
        # 已登录、非会员、尚未提交订单号 → 提示成为会员
        show_become_member = (not user_is_member(user)) and (not order_no)
        show_join_recruit_group = False
    else:
        username = "游客"
        userid = "0"
        show_become_member = False
        show_join_recruit_group = True

    return render_template(
        "index.html",
        username=username,
        userid=userid,
        show_become_member=show_become_member,
        show_join_recruit_group=show_join_recruit_group,
    )

