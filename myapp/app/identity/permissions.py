from __future__ import annotations

from typing import Dict, Iterable, Mapping

from app.models.config import get_config
from app.models.database import get_user_db

MANAGE_ACCOUNT_PERMISSION = "permission_manage_account"
SCRIPT_BITMAP_COLUMN = "permission_script_bitmap"
LIGHTBOARD_BITMAP_COLUMN = "permission_lightboard_bitmap"

DEFAULT_BITMAP_CONFIG = {
    "script_subsystem": {
        "permission_manage_own_editions": 0,
        "permission_manage_all_editions": 1,
        "permission_manage_create_editions": 2,
        "permission_storyteller": 3,
        "permission_storyteller_vocal": 4,
    },
    "lightboard_subsystem": {
        "permission_lightboard_create_event": 0,
        "permission_lightboard_edit_any_event": 1,
        "permission_lightboard_delete_any_event": 2,
    },
}

LEGACY_SCRIPT_COLUMNS = (
    "permission_manage_own_editions",
    "permission_manage_all_editions",
    "permission_manage_create_editions",
    "permission_storyteller",
    "permission_storyteller_vocal",
)

LEGACY_MANAGE_ACCOUNT_COLUMN = "permission_manage_accounts"

ASSOCIATION_ROLE_COLUMN = "association_role"
SOCIAL_ROLE_COLUMN = "social_role"
ACTIVITY_ORGANIZED_COUNT_COLUMN = "activity_organized_count"
ACTIVITY_JOINED_COUNT_COLUMN = "activity_joined_count"
ACTIVITY_ABSENT_COUNT_COLUMN = "activity_absent_count"
CONTACT_INFO_COLUMN = "contact_info"
EMAIL_COLUMN = "email"
EMAIL_VERIFIED_COLUMN = "email_verified"
MEMBER_ORDER_NO_COLUMN = "member_order_no"
MEMBER_REVIEW_NOTE_COLUMN = "member_review_note"

ASSOCIATION_ROLE_VALUES = ("普通玩家", "协会玩家", "核心玩家", "管理员")
SOCIAL_ROLE_VALUES = ("交大学生", "华师学生", "校外人员", "保密")
ASSOCIATION_ROLE_RANK = {
    "普通玩家": 0,
    "协会玩家": 1,
    "核心玩家": 2,
    "管理员": 3,
}


def _bool_like(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _to_uint64(value) -> int:
    if value is None:
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return result & ((1 << 64) - 1)


def get_permission_bitmap_config() -> Dict[str, Dict[str, int]]:
    try:
        config = get_config("permission_bitmap")
        if not isinstance(config, dict):
            return DEFAULT_BITMAP_CONFIG
    except Exception:
        return DEFAULT_BITMAP_CONFIG

    script = config.get("script_subsystem", {})
    lightboard = config.get("lightboard_subsystem", {})

    return {
        "script_subsystem": {
            name: int(bit)
            for name, bit in script.items()
            if isinstance(name, str)
        }
        or DEFAULT_BITMAP_CONFIG["script_subsystem"],
        "lightboard_subsystem": {
            name: int(bit)
            for name, bit in lightboard.items()
            if isinstance(name, str)
        }
        or DEFAULT_BITMAP_CONFIG["lightboard_subsystem"],
    }


def _build_bit_to_name_map(name_to_bit: Mapping[str, int]) -> Dict[int, str]:
    return {int(bit): name for name, bit in name_to_bit.items()}


def _row_column_set(conn) -> set[str]:
    columns = conn.execute("PRAGMA table_info(user_info)").fetchall()
    return {row["name"] for row in columns}


def _compute_script_bitmap_from_row(row: Mapping[str, object], config: Mapping[str, Dict[str, int]]) -> int:
    bitmap = _to_uint64(row.get(SCRIPT_BITMAP_COLUMN, 0))
    for name, bit in config["script_subsystem"].items():
        if _bool_like(row.get(name)):
            bitmap |= (1 << int(bit))
    return bitmap


def _permissions_to_bitmap(
    permission_names: Iterable[str],
    payload: Mapping[str, object],
    existing_bitmap: int,
    bit_map: Mapping[str, int],
) -> int:
    bitmap = _to_uint64(existing_bitmap)
    for name in permission_names:
        if name not in payload:
            continue
        bit = int(bit_map[name])
        if _bool_like(payload[name]):
            bitmap |= (1 << bit)
        else:
            bitmap &= ~(1 << bit)
    return _to_uint64(bitmap)


def ensure_user_permission_schema() -> None:
    config = get_permission_bitmap_config()
    conn = get_user_db()
    column_names = _row_column_set(conn)

    if MANAGE_ACCOUNT_PERMISSION not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {MANAGE_ACCOUNT_PERMISSION} BOOLEAN DEFAULT 0")
    if SCRIPT_BITMAP_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {SCRIPT_BITMAP_COLUMN} INTEGER DEFAULT 0")
    if LIGHTBOARD_BITMAP_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {LIGHTBOARD_BITMAP_COLUMN} INTEGER DEFAULT 0")
    if ASSOCIATION_ROLE_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {ASSOCIATION_ROLE_COLUMN} TEXT DEFAULT '普通玩家'")
    if SOCIAL_ROLE_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {SOCIAL_ROLE_COLUMN} TEXT DEFAULT '保密'")
    if ACTIVITY_ORGANIZED_COUNT_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {ACTIVITY_ORGANIZED_COUNT_COLUMN} INTEGER DEFAULT 0")
    if ACTIVITY_JOINED_COUNT_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {ACTIVITY_JOINED_COUNT_COLUMN} INTEGER DEFAULT 0")
    if ACTIVITY_ABSENT_COUNT_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {ACTIVITY_ABSENT_COUNT_COLUMN} INTEGER DEFAULT 0")
    if CONTACT_INFO_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {CONTACT_INFO_COLUMN} TEXT DEFAULT '保密'")
    if EMAIL_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {EMAIL_COLUMN} TEXT")
    if EMAIL_VERIFIED_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {EMAIL_VERIFIED_COLUMN} INTEGER DEFAULT 0")
    if MEMBER_ORDER_NO_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {MEMBER_ORDER_NO_COLUMN} TEXT")
    if MEMBER_REVIEW_NOTE_COLUMN not in column_names:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {MEMBER_REVIEW_NOTE_COLUMN} TEXT")

    try:
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_user_info_email ON user_info({EMAIL_COLUMN})"
        )
    except Exception:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )

    column_names = _row_column_set(conn)
    if LEGACY_MANAGE_ACCOUNT_COLUMN in column_names:
        conn.execute(
            f"""
            UPDATE user_info
            SET {MANAGE_ACCOUNT_PERMISSION} = COALESCE({MANAGE_ACCOUNT_PERMISSION}, 0) OR COALESCE({LEGACY_MANAGE_ACCOUNT_COLUMN}, 0)
            """
        )
    conn.execute(
        f"""
        UPDATE user_info
        SET
            {ASSOCIATION_ROLE_COLUMN} = CASE
                WHEN {ASSOCIATION_ROLE_COLUMN} IN ({",".join(["?"] * len(ASSOCIATION_ROLE_VALUES))}) THEN {ASSOCIATION_ROLE_COLUMN}
                ELSE '普通玩家'
            END,
            {SOCIAL_ROLE_COLUMN} = CASE
                WHEN {SOCIAL_ROLE_COLUMN} IN ({",".join(["?"] * len(SOCIAL_ROLE_VALUES))}) THEN {SOCIAL_ROLE_COLUMN}
                ELSE '保密'
            END,
            {CONTACT_INFO_COLUMN} = CASE
                WHEN {CONTACT_INFO_COLUMN} IS NULL OR TRIM({CONTACT_INFO_COLUMN}) = '' THEN '保密'
                ELSE {CONTACT_INFO_COLUMN}
            END,
            {ACTIVITY_ORGANIZED_COUNT_COLUMN} = MAX(COALESCE({ACTIVITY_ORGANIZED_COUNT_COLUMN}, 0), 0),
            {ACTIVITY_JOINED_COUNT_COLUMN} = MAX(COALESCE({ACTIVITY_JOINED_COUNT_COLUMN}, 0), 0),
            {ACTIVITY_ABSENT_COUNT_COLUMN} = MAX(COALESCE({ACTIVITY_ABSENT_COUNT_COLUMN}, 0), 0)
        """
        ,
        (*ASSOCIATION_ROLE_VALUES, *SOCIAL_ROLE_VALUES),
    )

    row_columns = [name for name in (SCRIPT_BITMAP_COLUMN, *LEGACY_SCRIPT_COLUMNS) if name in column_names]
    if row_columns:
        rows = conn.execute(f"SELECT id, {', '.join(row_columns)} FROM user_info").fetchall()
        for row in rows:
            row_dict = dict(row)
            new_bitmap = _compute_script_bitmap_from_row(row_dict, config)
            conn.execute(
                f"UPDATE user_info SET {SCRIPT_BITMAP_COLUMN}=? WHERE id=?",
                (new_bitmap, row_dict["id"]),
            )

    conn.commit()
    conn.close()


def enrich_user_permissions(user_info: Mapping[str, object]) -> Dict[str, object]:
    config = get_permission_bitmap_config()
    result = dict(user_info)

    result[MANAGE_ACCOUNT_PERMISSION] = _bool_like(result.get(MANAGE_ACCOUNT_PERMISSION)) or _bool_like(
        result.get(LEGACY_MANAGE_ACCOUNT_COLUMN)
    )
    # 保持旧字段对外兼容
    result[LEGACY_MANAGE_ACCOUNT_COLUMN] = result[MANAGE_ACCOUNT_PERMISSION]

    script_bitmap = _to_uint64(result.get(SCRIPT_BITMAP_COLUMN, 0))
    lightboard_bitmap = _to_uint64(result.get(LIGHTBOARD_BITMAP_COLUMN, 0))
    result[SCRIPT_BITMAP_COLUMN] = script_bitmap
    result[LIGHTBOARD_BITMAP_COLUMN] = lightboard_bitmap

    for name, bit in config["script_subsystem"].items():
        result[name] = bool(script_bitmap & (1 << int(bit)))

    for name, bit in config["lightboard_subsystem"].items():
        result[name] = bool(lightboard_bitmap & (1 << int(bit)))

    return result


def build_permission_update_fields(
    payload: Mapping[str, object],
    existing_user: Mapping[str, object],
) -> Dict[str, object]:
    config = get_permission_bitmap_config()
    current = enrich_user_permissions(existing_user)

    next_manage = current[MANAGE_ACCOUNT_PERMISSION]
    if MANAGE_ACCOUNT_PERMISSION in payload:
        next_manage = _bool_like(payload[MANAGE_ACCOUNT_PERMISSION])
    elif LEGACY_MANAGE_ACCOUNT_COLUMN in payload:
        next_manage = _bool_like(payload[LEGACY_MANAGE_ACCOUNT_COLUMN])

    script_map = config["script_subsystem"]
    lightboard_map = config["lightboard_subsystem"]

    script_bitmap = _permissions_to_bitmap(
        script_map.keys(),
        payload,
        current[SCRIPT_BITMAP_COLUMN],
        script_map,
    )
    lightboard_bitmap = _permissions_to_bitmap(
        lightboard_map.keys(),
        payload,
        current[LIGHTBOARD_BITMAP_COLUMN],
        lightboard_map,
    )

    update_fields = {
        MANAGE_ACCOUNT_PERMISSION: int(next_manage),
        SCRIPT_BITMAP_COLUMN: script_bitmap,
        LIGHTBOARD_BITMAP_COLUMN: lightboard_bitmap,
    }

    # 老列如果还在表中，保持同步，方便灰度迁移期回滚。
    existing_columns = set(existing_user.keys())
    if LEGACY_MANAGE_ACCOUNT_COLUMN in existing_columns:
        update_fields[LEGACY_MANAGE_ACCOUNT_COLUMN] = int(next_manage)
    for name in script_map:
        if name in LEGACY_SCRIPT_COLUMNS and name in existing_columns:
            update_fields[name] = int(bool(script_bitmap & (1 << int(script_map[name]))))

    return update_fields


def permission_bitmap_descriptions() -> Dict[str, Dict[int, str]]:
    config = get_permission_bitmap_config()
    return {
        "script_subsystem": _build_bit_to_name_map(config["script_subsystem"]),
        "lightboard_subsystem": _build_bit_to_name_map(config["lightboard_subsystem"]),
    }
