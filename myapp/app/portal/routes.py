from flask import Blueprint, render_template

from app.identity import get_current_user

portal_bp = Blueprint("portal", __name__, template_folder="templates")


@portal_bp.route("/")
def index():
    user = get_current_user(update_last_login=False)
    if user:
        username = user["name"]
        userid = user["id"]
    else:
        username = "游客"
        userid = "0"

    return render_template("index.html", username=username, userid=userid)

