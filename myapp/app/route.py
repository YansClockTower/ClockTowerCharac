from flask import request, render_template

from app.models.crypt import user_me

def register_routes(app):
    @app.route('/')
    def index():
        user = user_me()
        username = ""
        if user:
            username = user['name']
        else:
            username = "游客"

        return render_template("index.html",
            username=username)