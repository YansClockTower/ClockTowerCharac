from __future__ import annotations

from typing import Dict, Iterable, Mapping

from app.models.config import get_config
from app.models.database import get_user_db

MANAGE_ACCOUNT_PERMISSION = "permission_manage_account"
SCRIPT_BITMAP_COLUMN = "permission_script_bitmap"
LEGACY_LIGHTBOARD_BITMAP_COLUMN = "permission_lightboard_bitmap"

PERMISSION_STORYTELLER = "permission_storyteller"
PERMISSION_BOTC_EDITION_AUTHOR = "permission_botc_edition_author"
PERMISSION_TRPG_DM = "permission_trpg_dm"
PERMISSION_TRPG_MODULE_AUTHOR = "permission_trpg_module_author"
USER_PERMISSION_KEYS = (
    PERMISSION_STORYTELLER,
    PERMISSION_BOTC_EDITION_AUTHOR,
    PERMISSION_TRPG_DM,
    PERMISSION_TRPG_MODULE_AUTHOR,
)

# 旧 lightboard 独立列的位 → 合并进 script_subsystem 后的权限名
LEGACY_LIGHTBOARD_BITMAP_BITS = {
    "permission_create_official_event": 0,
    "permission_manage_all_event": 1,
    "permission_borrow_games": 2,
    "permission_manage_games": 3,
}

# 旧版 5 项剧本权限位图（仅用于迁移）
LEGACY_SCRIPT_BITMAP_CONFIG = {
    "permission_manage_own_editions": 0,
    "permission_manage_all_editions": 1,
    "permission_manage_create_editions": 2,
    "permission_storyteller": 3,
    "permission_storyteller_vocal": 4,
}

DEFAULT_BITMAP_CONFIG = {
    "script_subsystem": {
        PERMISSION_STORYTELLER: 0,
        PERMISSION_BOTC_EDITION_AUTHOR: 1,
        PERMISSION_TRPG_DM: 2,
        PERMISSION_TRPG_MODULE_AUTHOR: 3,
        "permission_create_official_event": 4,
        "permission_manage_all_event": 5,
        "permission_borrow_games": 6,
        "permission_manage_games": 7,
    },
}

LEGACY_SCRIPT_COLUMNS = (
    "permission_manage_own_editions",
    "permission_manage_all_editions",
    "permission_manage_create_editions",
    "permission_storyteller",
    "permission_storyteller_vocal",
)

LEGACY_EDITION_COLUMNS = (
    "permission_manage_own_editions",
    "permission_manage_all_editions",
    "permission_manage_create_editions",
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

ASSOCIATION_ROLE_VALUES = ("普通玩家", "协会玩家", "核心玩家", "干事", "管理员")
SOCIAL_ROLE_VALUES = ("交大学生", "华师学生", "校外人员", "保密")
ASSOCIATION_ROLE_RANK = {
    "普通玩家": 0,
    "协会玩家": 1,
    "核心玩家": 2,
    "干事": 3,
    "管理员": 4,
}
MEMBER_RANK = ASSOCIATION_ROLE_RANK["协会玩家"]
STAFF_RANK = ASSOCIATION_ROLE_RANK["干事"]
ADMIN_RANK = ASSOCIATION_ROLE_RANK["管理员"]


def association_role_of(user) -> str:
    if user is None:
        return "普通玩家"
    role = user.get(ASSOCIATION_ROLE_COLUMN, "普通玩家") if isinstance(user, dict) else user[ASSOCIATION_ROLE_COLUMN]
    role = role or "普通玩家"
    return role if role in ASSOCIATION_ROLE_RANK else "普通玩家"


def association_role_rank(user) -> int:
    """协会身份等级，缺省 / 未知身份为 0（普通玩家）。"""
    return ASSOCIATION_ROLE_RANK.get(association_role_of(user), 0)


def user_is_admin(user) -> bool:
    """管理员：association_rank == 4。"""
    return association_role_rank(user) == ADMIN_RANK


def user_is_staff(user) -> bool:
    """干事及以上（association_rank >= 3），含布鸽活动发布/活动室权限。"""
    return association_role_rank(user) >= STAFF_RANK


def _legacy_storyteller_from_row(row: Mapping[str, object], bitmap: int) -> bool:
    if any(_bool_like(row.get(name)) for name in ("permission_storyteller", "permission_storyteller_vocal")):
        return True
    for name in ("permission_storyteller", "permission_storyteller_vocal"):
        bit = LEGACY_SCRIPT_BITMAP_CONFIG.get(name)
        if bit is not None and (bitmap & (1 << bit)):
            return True
    return False


def _legacy_botc_author_from_row(row: Mapping[str, object], bitmap: int) -> bool:
    if any(_bool_like(row.get(name)) for name in LEGACY_EDITION_COLUMNS):
        return True
    for name in LEGACY_EDITION_COLUMNS:
        bit = LEGACY_SCRIPT_BITMAP_CONFIG.get(name)
        if bit is not None and (bitmap & (1 << bit)):
            return True
    return False


def _bitmap_mask(bit_map: Mapping[str, int]) -> int:
    mask = 0
    for bit in bit_map.values():
        mask |= 1 << int(bit)
    return mask


def _merge_legacy_lightboard_bitmap(
    script_bitmap: int,
    lightboard_bitmap: int,
    script_map: Mapping[str, int],
) -> int:
    merged = _to_uint64(script_bitmap)
    for name, old_bit in LEGACY_LIGHTBOARD_BITMAP_BITS.items():
        new_bit = script_map.get(name)
        if new_bit is None:
            continue
        if lightboard_bitmap & (1 << int(old_bit)):
            merged |= 1 << int(new_bit)
    return merged


def _normalize_script_bitmap(row: Mapping[str, object], config: Mapping[str, Dict[str, int]]) -> int:
    """将旧列/旧 lightboard 列同步为 script_subsystem 定义的权限位。"""
    raw_bitmap = _to_uint64(row.get(SCRIPT_BITMAP_COLUMN, 0))
    script_map = config["script_subsystem"]
    permission_mask = _bitmap_mask(script_map)

    if LEGACY_LIGHTBOARD_BITMAP_COLUMN in row:
        raw_bitmap = _merge_legacy_lightboard_bitmap(
            raw_bitmap,
            _to_uint64(row.get(LEGACY_LIGHTBOARD_BITMAP_COLUMN, 0)),
            script_map,
        )

    storyteller_bit = int(script_map[PERMISSION_STORYTELLER])
    botc_bit = int(script_map[PERMISSION_BOTC_EDITION_AUTHOR])
    has_legacy_columns = any(_bool_like(row.get(name)) for name in LEGACY_SCRIPT_COLUMNS)

    if has_legacy_columns:
        new_bitmap = raw_bitmap & permission_mask
        if _legacy_storyteller_from_row(row, raw_bitmap):
            new_bitmap |= 1 << storyteller_bit
        if _legacy_botc_author_from_row(row, raw_bitmap):
            new_bitmap |= 1 << botc_bit
        return _to_uint64(new_bitmap & permission_mask)

    return _to_uint64(raw_bitmap & permission_mask)


def _payload_to_user_permissions(payload: Mapping[str, object], current: Mapping[str, object]) -> Dict[str, bool]:
    """解析更新载荷中的用户权限（兼容旧字段名）。"""
    perms = {name: _bool_like(current.get(name, False)) for name in USER_PERMISSION_KEYS}

    if PERMISSION_STORYTELLER in payload:
        perms[PERMISSION_STORYTELLER] = _bool_like(payload[PERMISSION_STORYTELLER])
    elif "permission_storyteller" in payload or "permission_storyteller_vocal" in payload:
        perms[PERMISSION_STORYTELLER] = _bool_like(payload.get("permission_storyteller")) or _bool_like(
            payload.get("permission_storyteller_vocal")
        )

    if PERMISSION_BOTC_EDITION_AUTHOR in payload:
        perms[PERMISSION_BOTC_EDITION_AUTHOR] = _bool_like(payload[PERMISSION_BOTC_EDITION_AUTHOR])
    elif any(key in payload for key in LEGACY_EDITION_COLUMNS):
        perms[PERMISSION_BOTC_EDITION_AUTHOR] = any(_bool_like(payload.get(key)) for key in LEGACY_EDITION_COLUMNS)

    for name in (PERMISSION_TRPG_DM, PERMISSION_TRPG_MODULE_AUTHOR):
        if name in payload:
            perms[name] = _bool_like(payload[name])

    return {name: bool(perms[name]) for name in USER_PERMISSION_KEYS}


def _permissions_dict_to_script_bitmap(perms: Mapping[str, bool], script_map: Mapping[str, int]) -> int:
    bitmap = 0
    for name in USER_PERMISSION_KEYS:
        if perms.get(name) and name in script_map:
            bitmap |= 1 << int(script_map[name])
    return _to_uint64(bitmap)


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

    script = {
        name: int(bit)
        for name, bit in config.get("script_subsystem", {}).items()
        if isinstance(name, str)
    }
    # 兼容旧 config：lightboard_subsystem 合并进 script_subsystem（bit 4 起）
    lightboard = config.get("lightboard_subsystem", {})
    for name, bit in lightboard.items():
        if isinstance(name, str) and name not in script:
            script[name] = int(bit) + 4

    return {
        "script_subsystem": script or DEFAULT_BITMAP_CONFIG["script_subsystem"],
    }


def _build_bit_to_name_map(name_to_bit: Mapping[str, int]) -> Dict[int, str]:
    return {int(bit): name for name, bit in name_to_bit.items()}


def _row_column_set(conn) -> set[str]:
    columns = conn.execute("PRAGMA table_info(user_info)").fetchall()
    return {row["name"] for row in columns}


def _compute_script_bitmap_from_row(row: Mapping[str, object], config: Mapping[str, Dict[str, int]]) -> int:
    return _normalize_script_bitmap(row, config)


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

    conn.execute(
        f"""
        UPDATE user_info
        SET {MANAGE_ACCOUNT_PERMISSION} = CASE
            WHEN {ASSOCIATION_ROLE_COLUMN} = ? THEN 1
            ELSE 0
        END
        """,
        (ASSOCIATION_ROLE_VALUES[-1],),
    )
    if LEGACY_MANAGE_ACCOUNT_COLUMN in column_names:
        conn.execute(
            f"""
            UPDATE user_info
            SET {LEGACY_MANAGE_ACCOUNT_COLUMN} = {MANAGE_ACCOUNT_PERMISSION}
            """
        )

    column_names = _row_column_set(conn)
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

    row_columns = [
        name
        for name in (
            SCRIPT_BITMAP_COLUMN,
            LEGACY_LIGHTBOARD_BITMAP_COLUMN,
            ASSOCIATION_ROLE_COLUMN,
            *LEGACY_SCRIPT_COLUMNS,
        )
        if name in column_names
    ]
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
    script_map = config["script_subsystem"]

    script_bitmap = _normalize_script_bitmap(result, config)
    result[SCRIPT_BITMAP_COLUMN] = script_bitmap

    for name, bit in script_map.items():
        result[name] = bool(script_bitmap & (1 << int(bit)))

    is_admin = user_is_admin(result)

    result[ASSOCIATION_ROLE_COLUMN] = association_role_of(result)
    result["association_rank"] = association_role_rank(result)

    result[MANAGE_ACCOUNT_PERMISSION] = is_admin
    result[LEGACY_MANAGE_ACCOUNT_COLUMN] = is_admin

    # 旧字段别名，供现有业务代码只读使用
    storyteller = result[PERMISSION_STORYTELLER]
    botc_author = result[PERMISSION_BOTC_EDITION_AUTHOR]
    result["permission_storyteller_vocal"] = storyteller
    result["permission_manage_own_editions"] = botc_author
    result["permission_manage_create_editions"] = botc_author
    result["permission_manage_all_editions"] = botc_author or is_admin

    return result


def build_permission_update_fields(
    payload: Mapping[str, object],
    existing_user: Mapping[str, object],
) -> Dict[str, object]:
    config = get_permission_bitmap_config()
    current = enrich_user_permissions(existing_user)
    script_map = config["script_subsystem"]

    perms = _payload_to_user_permissions(payload, current)
    script_bitmap = _to_uint64(current[SCRIPT_BITMAP_COLUMN])
    for name, enabled in perms.items():
        bit = int(script_map[name])
        if enabled:
            script_bitmap |= 1 << bit
        else:
            script_bitmap &= ~(1 << bit)
    script_bitmap = _permissions_to_bitmap(
        (name for name in script_map if name not in USER_PERMISSION_KEYS),
        payload,
        script_bitmap,
        script_map,
    )

    update_fields = {
        SCRIPT_BITMAP_COLUMN: script_bitmap,
    }

    existing_columns = set(existing_user.keys())
    if LEGACY_MANAGE_ACCOUNT_COLUMN in existing_columns:
        update_fields[LEGACY_MANAGE_ACCOUNT_COLUMN] = int(user_is_admin(current))
    if MANAGE_ACCOUNT_PERMISSION in existing_columns:
        update_fields[MANAGE_ACCOUNT_PERMISSION] = int(user_is_admin(current))

    for name in LEGACY_SCRIPT_COLUMNS:
        if name not in existing_columns:
            continue
        if name in ("permission_storyteller", "permission_storyteller_vocal"):
            update_fields[name] = int(perms[PERMISSION_STORYTELLER])
        elif name in LEGACY_EDITION_COLUMNS:
            update_fields[name] = int(perms[PERMISSION_BOTC_EDITION_AUTHOR])

    return update_fields


def permission_bitmap_descriptions() -> Dict[str, Dict[int, str]]:
    config = get_permission_bitmap_config()
    return {
        "script_subsystem": _build_bit_to_name_map(config["script_subsystem"]),
    }
