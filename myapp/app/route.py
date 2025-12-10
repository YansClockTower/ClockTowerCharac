from flask import request, render_template

from app.models.crypt import user_me

def register_routes(app):
    @app.route('/')
    def index():
        user = user_me()
        username = ""
        userid = ""
        if user:
            username = user['name']
            userid = user['id']
        else:
            username = "游客"
            userid = "0"

        return render_template("index.html",
            username=username,
            userid=userid)