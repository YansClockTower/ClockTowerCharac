

import sqlite3

# 创建数据库文件（如果已存在则连接）
conn = sqlite3.connect('character_latest.sqlite')

conn.execute('''CREATE TABLE character_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image TEXT,
    name TEXT UNIQUE,
    team TEXT,
    ability TEXT,
    setup BOOLEAN,
    firstNight INTEGER,
    otherNight INTEGER,
    firstNightReminder TEXT,
    otherNightReminder TEXT,
    reminders TEXT,
    remindersGlobal TEXT,
    tags TEXT,
    fromEdition INTEGER,
    lastUpdated INTEGER
);''')

conn.execute('''CREATE TABLE character_almanac (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    designer TEXT,
    drawer TEXT,
    flavor TEXT,
    overview TEXT,
    examples TEXT,
    howToRun TEXT,
    tips TEXT,
    lastUpdated INTEGER
);''')


conn.execute('''CREATE TABLE character_jinxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character1 INTEGER,
    character2 INTEGER,
    ability TEXT,
    lastUpdated INTEGER
);''')

conn.execute('''CREATE TABLE character_tags (
    id INTEGER PRIMARY KEY,
    name TEXT,
    explain TEXT
);''')

conn.commit()

# 关闭连接
conn.close()

conn = sqlite3.connect('edition_latest.sqlite')

conn.execute('''CREATE TABLE editions_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logo TEXT,
    name TEXT,
    description TEXT,
    characterList TEXT,
    version TEXT,
    author TEXT,
    minPlayer INTEGER,
    maxPlayer INTEGER,
    synopsis TEXT,
    overview TEXT,
    changeLog TEXT,
    guidanceForST TEXT,
    states TEXT,
    lastUpdated INTEGER
);''')

conn.commit()

# 关闭连接
conn.close()