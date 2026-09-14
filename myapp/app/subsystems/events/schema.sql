DROP TABLE IF EXISTS events;
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signcode TEXT NOT NULL,
    name TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT '其他' CHECK(event_type IN ('轻桌游聚会','布鸽桌游活动','德州扑克','德式桌游','狼人杀','血染钟楼','其他')),
    inviter TEXT NOT NULL,
    location TEXT NOT NULL,
    starttime TEXT NOT NULL,
    locktime TEXT NOT NULL,
    description TEXT,
    minplayer INTEGER,
    maxplayer INTEGER
);

DROP TABLE IF EXISTS attendinfo;
CREATE TABLE attendinfo (
    entryid INTEGER PRIMARY KEY AUTOINCREMENT,
    eventid INTEGER NOT NULL,
    player TEXT NOT NULL,
    note TEXT,
    friend INTEGER DEFAULT 0,
    signed INTEGER DEFAULT 0,
    UNIQUE(eventid, player),
    FOREIGN KEY(eventid) REFERENCES events(id) ON DELETE CASCADE
);

DROP TABLE IF EXISTS attendrecord;
CREATE TABLE attendrecord (
    entryid INTEGER PRIMARY KEY AUTOINCREMENT,
    player TEXT NOT NULL,
    eventtime TEXT,
    eventname TEXT NOT NULL,
    signed INTEGER DEFAULT 0
);

-- 固定聚会（与自由聚会并列，独立表）
DROP TABLE IF EXISTS fixed_table_attend;
DROP TABLE IF EXISTS fixed_tables;
DROP TABLE IF EXISTS fixed_events;

CREATE TABLE fixed_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signcode TEXT NOT NULL,
    name TEXT NOT NULL,
    inviter TEXT NOT NULL,
    location TEXT NOT NULL,
    starttime TEXT NOT NULL,
    locktime TEXT NOT NULL,
    description TEXT,
    minplayer INTEGER,
    maxplayer INTEGER
);

CREATE TABLE fixed_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixed_event_id INTEGER NOT NULL,
    host TEXT NOT NULL,
    board_game_id INTEGER NOT NULL,
    board_game_name TEXT NOT NULL,
    min_players INTEGER,
    max_players INTEGER NOT NULL,
    owner_name TEXT NOT NULL,
    holder_name TEXT,
    owner_confirmed INTEGER NOT NULL DEFAULT 0,
    holder_confirmed INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(fixed_event_id) REFERENCES fixed_events(id) ON DELETE CASCADE
);

CREATE TABLE fixed_table_attend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL,
    fixed_event_id INTEGER NOT NULL,
    player TEXT NOT NULL,
    note TEXT,
    signed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(fixed_event_id, player),
    UNIQUE(table_id, player),
    FOREIGN KEY(table_id) REFERENCES fixed_tables(id) ON DELETE CASCADE,
    FOREIGN KEY(fixed_event_id) REFERENCES fixed_events(id) ON DELETE CASCADE
);
