import json
import string
from flask import Blueprint, render_template, request, make_response, send_file, jsonify
from io import BytesIO

from app.models.database import (
    get_character_db
)
from app.models.export_edition_json import generate_edition_json

api_bp = Blueprint("api", __name__)

@api_bp.route('/api/character_info', methods=['POST'])
def character_info():
    names = request.json.get('names', [])
    found = {}
    not_found = []

    conn = get_character_db()
    cursor = conn.cursor()
    
    for cid in names:
        name = cid.strip(string.whitespace + string.punctuation)
        cursor.execute("SELECT * FROM character_info WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            # 假设row是tuple，转成dict
            found[cid] = {
                "id": row["id"],
                "name": row["name"],
                "team": row["team"],
                "ability": row["ability"],
                "image": row["image"],
                "fromEdition": row["fromEdition"]
                # 你需要的其他字段
            }
        else:
            not_found.append(cid)
    return jsonify({"found": found, "not_found": not_found})
