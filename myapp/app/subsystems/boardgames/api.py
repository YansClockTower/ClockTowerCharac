"""Data access for registered board games (used by routes, not HTTP)."""

from typing import Any, Optional

from app.subsystems.boardgames.dbutil import get_db


def borrower_name(owner: Optional[str], current_holder: Optional[str]) -> Optional[str]:
    """借用者。未填写，或与所有者相同，都表示未借出。"""
    holder = (current_holder or "").strip()
    if not holder or holder == (owner or "").strip():
        return None
    return holder


def _with_borrower(row: dict[str, Any]) -> dict[str, Any]:
    row["borrower"] = borrower_name(row.get("owner"), row.get("current_holder"))
    return row


def list_browse_rows():
    """浏览列表：含所有者、借用者与存放地点（存放地点由页面按查看者决定是否展示）。"""
    db = get_db()
    cur = db.execute(
        """
        SELECT id, board_game_name, image_path, owner, current_holder, current_storage_location
        FROM registered_board_games
        ORDER BY id DESC
        """
    )
    return [_with_borrower(dict(row)) for row in cur.fetchall()]


ASSOCIATION_GAME_OWNER = "布鸽桌游协会"

# 开桌富下拉按所有者筛选时可选的用户（影编码阶段固定名单）
PICKER_OWNER_FILTERS = (
    ASSOCIATION_GAME_OWNER,
    "不是鱼子酱",
    "Upkeep",
    "Doing",
)


def list_picker_rows():
    """开桌选桌游用：含所有者、借用者与人数上下限。"""
    db = get_db()
    cur = db.execute(
        """
        SELECT id, board_game_name, owner, current_holder, min_players, max_players, image_path
        FROM registered_board_games
        ORDER BY board_game_name COLLATE NOCASE ASC, id DESC
        """
    )
    return [_with_borrower(dict(row)) for row in cur.fetchall()]


def get_game_by_id(game_id: int) -> Optional[dict[str, Any]]:
    db = get_db()
    row = db.execute(
        "SELECT * FROM registered_board_games WHERE id = ?",
        (game_id,),
    ).fetchone()
    return _with_borrower(dict(row)) if row else None


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


def update_registered_game(
    game_id: int,
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
) -> bool:
    db = get_db()
    playing_val = str(playing_time) if playing_time is not None else None
    cur = db.execute(
        """
        UPDATE registered_board_games
        SET board_game_name = ?,
            game_type = ?,
            min_players = ?,
            max_players = ?,
            recommended_players = ?,
            playing_time = ?,
            description = ?,
            image_path = ?,
            owner = ?,
            current_holder = ?,
            current_storage_location = ?
        WHERE id = ?
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
            game_id,
        ),
    )
    db.commit()
    return cur.rowcount > 0


def delete_registered_game(game_id: int) -> bool:
    db = get_db()
    cur = db.execute("DELETE FROM registered_board_games WHERE id = ?", (game_id,))
    db.commit()
    return cur.rowcount > 0
