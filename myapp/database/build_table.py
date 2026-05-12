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

# 登记桌游：新建数据库 board_games.sqlite，表 registered_board_games
# 在 myapp/database 目录下执行：python3 build_table.py
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