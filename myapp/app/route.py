from flask import request, render_template
from .models.database import get_character_db, get_editions_info, get_filtered_characters

def register_routes(app):
    @app.route('/')
    def index():
        return render_template("index.html")