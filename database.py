import json
import uuid
from datetime import datetime, timedelta
import psycopg  # <-- psycopg3 import (psycopg2 yerine)
from urllib.parse import urlparse
import bcrypt
from config import DATABASE_URL, DEVELOPER_PASSWORD
import logging

logger = logging.getLogger(__name__)

SESSION_MAP = {}  # session_id: username

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL bulunamadı!")
    # psycopg3: connect(dsn=...)
    conn = psycopg.connect(conninfo=DATABASE_URL)
    return conn

def init_db():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                premium_until TIMESTAMP NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                messages TEXT NOT NULL,
                last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
    conn.commit()
    conn.close()
    logger.info("DB başlatıldı.")

def get_user_id(username: str) -> int:
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        row = cursor.fetchone()
    conn.close()
    return row[0] if row else None  # psycopg3: row tuple, index 0

def get_current_user():
    # request global hack'i aynı (app.py'de set ediliyor)
    if 'request' in globals():
        session_id = request.cookies.get('session_id')
        return SESSION_MAP.get(session_id)
    return None

def is_user_premium(username: str) -> bool:
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT premium_until FROM users
            WHERE username = %s AND premium_until > NOW()
        """, (username,))
        row = cursor.fetchone()
    conn.close()
    return bool(row)

def get_premium_until(username: str) -> datetime:
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT premium_until FROM users WHERE username = %s", (username,))
        row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]  # tuple
    return None

def create_user(username: str, password: str):
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        try:
            cursor.execute("""
                INSERT INTO users (username, password, premium_until)
                VALUES (%s, %s, NOW())
            """, (username, hashed))
            conn.commit()
            return True
        except psycopg.IntegrityError:  # <-- psycopg3 exception
            return False
        finally:
            conn.close()

def authenticate_user(username: str, password: str) -> bool:
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
        row = cursor.fetchone()
    conn.close()
    if row:
        return bcrypt.checkpw(password.encode('utf-8'), row[0].encode('utf-8'))
    return False

def check_admin_auth(username: str, password: str) -> bool:
    from config import DEVELOPER_USERNAME, DEVELOPER_PASSWORD
    return username == DEVELOPER_USERNAME and password == DEVELOPER_PASSWORD

def grant_premium(username: str, days: int = 30):
    new_expiry = datetime.now() + timedelta(days=days)
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE users SET premium_until = %s WHERE username = %s
        """, (new_expiry, username))
        conn.commit()
        affected = cursor.rowcount
    conn.close()
    return affected > 0

def save_chat(username: str, chat_name: str, messages: list) -> str:
    user_id = get_user_id(username)
    if not user_id:
        return None
    chat_id = str(uuid.uuid4())
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO chats (id, user_id, name, messages, last_updated)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (chat_id, user_id, chat_name, json.dumps(messages)))
        conn.commit()
    conn.close()
    return chat_id

def get_user_chats(username: str) -> list:
    user_id = get_user_id(username)
    if not user_id:
        return []
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, messages, last_updated
            FROM chats
            WHERE user_id = %s AND last_updated > NOW() - INTERVAL '20 days'
            ORDER BY last_updated DESC
        """, (user_id,))
        rows = cursor.fetchall()
    conn.close()
    chats = []
    for row in rows:
        chats.append({
            'id': row[0],
            'name': row[1],
            'messages': json.loads(row[2]),
            'last_updated': row[3].isoformat()
        })
    return chats

def load_chat(username: str, chat_id: str) -> dict:
    user_id = get_user_id(username)
    if not user_id:
        return None
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT name, messages, last_updated
            FROM chats
            WHERE id = %s AND user_id = %s
        """, (chat_id, user_id))
        row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'id': chat_id,
            'name': row[0],
            'messages': json.loads(row[1]),
            'last_updated': row[2].isoformat()
        }
    return None

def delete_chat(username: str, chat_id: str) -> bool:
    user_id = get_user_id(username)
    if not user_id:
        return False
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            DELETE FROM chats WHERE id = %s AND user_id = %s
        """, (chat_id, user_id))
        conn.commit()
        affected = cursor.rowcount
    conn.close()
    return affected > 0
