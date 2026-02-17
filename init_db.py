import sqlite3
import os

os.makedirs("instance", exist_ok=True)

conn = sqlite3.connect("instance/sports.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    role TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS player_profiles (
    user_id INTEGER PRIMARY KEY,
    sport TEXT,
    role TEXT,
    description TEXT,
    location TEXT,
    skills TEXT,
    photo TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS team_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER,
    role_needed TEXT,
    location TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    receiver_id INTEGER,
    status TEXT
)
""")

conn.commit()
conn.close()
print("Database initialized")
