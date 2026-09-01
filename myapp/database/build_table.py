import sqlite3

# conn = sqlite3.connect('user_latest.sqlite')

# conn.execute('''CREATE TABLE user_info (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT UNIQUE,
#     password_hash TEXT,
#     icon TEXT,
#     title TEXT,
#     permission_manage_account BOOLEAN DEFAULT 0,
#     permission_script_bitmap INTEGER DEFAULT 0,
#     permission_lightboard_bitmap INTEGER DEFAULT 0,
#     association_role TEXT DEFAULT '普通玩家' CHECK(association_role IN ('普通玩家', '协会玩家', '核心玩家', '管理员')),
#     social_role TEXT DEFAULT '保密' CHECK(social_role IN ('交大学生', '华师学生', '校外人员', '保密')),
#     contact_info TEXT DEFAULT '保密',
#     activity_organized_count INTEGER DEFAULT 0 CHECK(activity_organized_count >= 0),
#     activity_joined_count INTEGER DEFAULT 0 CHECK(activity_joined_count >= 0),
#     activity_absent_count INTEGER DEFAULT 0 CHECK(activity_absent_count >= 0),
#     email TEXT UNIQUE,
#     email_verified INTEGER DEFAULT 0,
#     member_order_no TEXT,
#     member_review_note TEXT,
#     lastLogin INTEGER
# );''')

# conn.commit()

# # 关闭连接
# conn.close()


# # 创建数据库文件（如果已存在则连接）
# conn = sqlite3.connect('character_latest.sqlite')

# conn.execute('''CREATE TABLE character_info (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     image TEXT,
#     name TEXT UNIQUE,
#     team TEXT,
#     ability TEXT,
#     setup BOOLEAN,
#     firstNight INTEGER,
#     otherNight INTEGER,
#     firstNightReminder TEXT,
#     otherNightReminder TEXT,
#     reminders TEXT,
#     remindersGlobal TEXT,
#     tags TEXT,
#     fromEdition INTEGER,
#     lastUpdated INTEGER
# );''')

# conn.execute('''CREATE TABLE character_almanac (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     designer TEXT,
#     drawer TEXT,
#     flavor TEXT,
#     overview TEXT,
#     examples TEXT,
#     howToRun TEXT,
#     tips TEXT,
#     lastUpdated INTEGER
# );''')


# conn.execute('''CREATE TABLE character_jinxes (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     character1 INTEGER,
#     character2 INTEGER,
#     ability TEXT,
#     lastUpdated INTEGER
# );''')

# conn.execute('''CREATE TABLE character_tags (
#     id INTEGER PRIMARY KEY,
#     name TEXT,
#     explain TEXT
# );''')

# conn.commit()

# # 关闭连接
# conn.close()

# conn = sqlite3.connect('edition_latest.sqlite')

# conn.execute('''CREATE TABLE editions_info (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     logo TEXT,
#     name TEXT,
#     description TEXT,
#     characterList TEXT,
#     version TEXT,
#     author TEXT,
#     minPlayer INTEGER,
#     maxPlayer INTEGER,
#     synopsis TEXT,
#     overview TEXT,
#     changeLog TEXT,
#     guidanceForST TEXT,
#     states TEXT,
#     lastUpdated INTEGER
# );''')

# conn.commit()

# # 关闭连接
# conn.close()

# 在 myapp/database 目录下执行：python3 build_table.py

# 登记桌游：board_games.sqlite
conn = sqlite3.connect("board_games.sqlite")
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS registered_board_games (
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
conn.commit()
conn.close()
print("ok: board_games.sqlite")

# 微信二维码收款账单库：空表 wechat_qr_income（与 user / events 分离）
conn = sqlite3.connect("wechat_qr_income.sqlite")
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS wechat_qr_income (
        order_no TEXT PRIMARY KEY,
        peer TEXT NOT NULL,
        note TEXT,
        source_file TEXT,
        imported_at TEXT NOT NULL,
        redeemed INTEGER DEFAULT 0,
        redeemed_by TEXT,
        redeemed_at TEXT
    );
    """
)
conn.commit()
conn.close()
print("ok: wechat_qr_income.sqlite")

# 用户库：为已有 user_info 补邮箱 / 会员订单号列（幂等）
conn = sqlite3.connect("user_latest.sqlite")
user_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_info)").fetchall()}
if not user_cols:
    raise SystemExit("user_latest.sqlite 中没有 user_info 表，请先创建用户库")

_user_alters = [
    ("email", "TEXT"),
    ("email_verified", "INTEGER DEFAULT 0"),
    ("member_order_no", "TEXT"),
    ("member_review_note", "TEXT"),
]
for name, decl in _user_alters:
    if name not in user_cols:
        conn.execute(f"ALTER TABLE user_info ADD COLUMN {name} {decl}")
        print(f"ok: user_info ADD COLUMN {name}")
    else:
        print(f"skip: user_info.{name} already exists")

try:
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_info_email ON user_info(email)")
except Exception as exc:
    print(f"skip unique index on email: {exc}")

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
    );
    """
)
conn.commit()
conn.close()
print("ok: user_latest.sqlite email / member_order columns")
