DROP TABLE IF EXISTS events;
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signcode TEXT NOT NULL,
    name TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT '其他' CHECK(event_type IN ('轻桌游聚会','德州扑克','德式桌游','狼人杀','血染钟楼','其他')),
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
