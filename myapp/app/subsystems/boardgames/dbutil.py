import os
import sqlite3

from flask import g

from app.models.config import get_config


def _board_games_db_path():
    if get_config("development"):
        base_path = get_config("database_path_dev")
    else:
        base_path = get_config("database_path")
    return os.path.join(base_path, "board_games.sqlite")


def get_db():
    db = getattr(g, "_board_games_db", None)
    if db is None:
        db = g._board_games_db = sqlite3.connect(_board_games_db_path())
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        _ensure_registered_board_games_schema(db)
    return db


def _ensure_registered_board_games_schema(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='registered_board_games'"
    ).fetchone()
    if not row:
        db.execute(
            """
            CREATE TABLE registered_board_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_game_name TEXT NOT NULL,
                game_type TEXT,
                min_players INTEGER,
                max_players INTEGER,
                recommended_players INTEGER,
                playing_time TEXT,
                description TEXT,
                image_path TEXT,
                owner TEXT NOT NULL,
                current_holder TEXT,
                current_storage_location TEXT
            );
            """
        )
        db.commit()
        return
    columns = {r["name"] for r in db.execute("PRAGMA table_info(registered_board_games)").fetchall()}
    if "recommended_players" not in columns:
        db.execute("ALTER TABLE registered_board_games ADD COLUMN recommended_players INTEGER")
        db.commit()


def close_db(e=None):
    db = getattr(g, "_board_games_db", None)
    if db is not None:
        db.close()
        g._board_games_db = None
