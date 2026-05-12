"""Data access for registered board games (used by routes, not HTTP)."""

from typing import Any, Optional

from app.subsystems.boardgames.dbutil import get_db


def list_browse_rows():
    """Return dict rows with id, board_game_name, image_path for browse UI."""
    db = get_db()
    cur = db.execute(
        """
        SELECT id, board_game_name, image_path
        FROM registered_board_games
        ORDER BY id DESC
        """
    )
    return [dict(row) for row in cur.fetchall()]


def get_game_by_id(game_id: int) -> Optional[dict[str, Any]]:
    db = get_db()
    row = db.execute(
        "SELECT * FROM registered_board_games WHERE id = ?",
        (game_id,),
    ).fetchone()
    return dict(row) if row else None


def create_registered_game(
    *,
    board_game_name: str,
    game_type: Optional[str],
    min_players: Optional[int],
    max_players: Optional[int],
    recommended_players: Optional[int],
    playing_time: Optional[int],
    description: Optional[str],
    image_path: Optional[str],
    owner: str,
    current_holder: Optional[str],
    current_storage_location: Optional[str],
) -> int:
    db = get_db()
    playing_val = str(playing_time) if playing_time is not None else None
    cur = db.execute(
        """
        INSERT INTO registered_board_games (
            board_game_name,
            game_type,
            min_players,
            max_players,
            recommended_players,
            playing_time,
            description,
            image_path,
            owner,
            current_holder,
            current_storage_location
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            board_game_name,
            game_type,
            min_players,
            max_players,
            recommended_players,
            playing_val,
            description,
            image_path,
            owner,
            current_holder,
            current_storage_location,
        ),
    )
    db.commit()
    return int(cur.lastrowid)
