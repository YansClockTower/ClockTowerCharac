from flask import request, render_template
from .models.database import get_character_db, get_editions_info, get_filtered_characters

def register_routes(app):
    @app.route('/')
    def index():
        team_filter = request.args.get('team', '')
        edition_filter = request.args.get('fromEdition', type=int)
        search_query = request.args.get('q', '')

        characters = get_filtered_characters(team_filter, edition_filter, search_query)

        conn = get_character_db()
        teams = conn.execute('SELECT DISTINCT team FROM character_info WHERE team != ""').fetchall()
        conn.close()

        editions_info = get_editions_info()

        return render_template(
            'index.html',
            characters=characters,
            teams=teams,
            editions_info=editions_info,
            current_team=team_filter,
            current_edition=edition_filter,
            current_query=search_query
        )
