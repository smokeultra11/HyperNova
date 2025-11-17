import json
import uuid
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL bulunamadı!")
    url = urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    conn.cursor_factory = RealDictCursor
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    cursor.close()
    conn.close()
    logger.info("DB başlatıldı.")

# CRUD fonksiyonları (get_user_id, create_user, save_chat, vs. aynı, ama bcrypt ile hash'le)
import bcrypt  # Şifre hash için

def create_user(username: str, password: str):
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (username, password, premium_until)
            VALUES (%s, %s, NOW())
        """, (username, hashed.decode('utf-8')))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        return False
    finally:
        cursor.close()
        conn.close()

# Diğer fonksiyonlar: authenticate_user (bcrypt.checkpw ile), get_user_chats, load_chat, delete_chat, is_user_premium, grant_premium...
# (Tüm DB fonksiyonlarını buraya taşı, aynı kod)
