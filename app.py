import os
import logging
from flask import Flask, request, render_template, redirect, url_for
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database import init_db, get_current_user  # get_current_user için request global
from auth import auth_bp
from chat import chat_bp
from admin import admin_bp
from config import UI_TRANSLATIONS

app = Flask(__name__)
CORS(app)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["60 per hour"])

# Global request for database
app.config['global_request'] = None  # Hacky, ama çalışır; gerçekte context kullan

@app.before_request
def before_request():
    app.config['global_request'] = request

def get_current_user():
    from database import SESSION_MAP
    session_id = app.config['global_request'].cookies.get('session_id')
    return SESSION_MAP.get(session_id)

# Blueprints
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(chat_bp, url_prefix='/api')
app.register_blueprint(admin_bp)

@app.route('/')
def index():
    lang = request.cookies.get('lang', 'en')
    translations = UI_TRANSLATIONS[lang]
    # index.html'i render et, translations geç
    with open('templates/index.html', 'r') as f:
        html = f.read().replace('{{ translations }}', str(translations))  # Basit replace, gerçekte Jinja kullan
    return html

init_db()

# Developer user ekle
from database import get_db_connection, DEVELOPER_USERNAME, DEVELOPER_PASSWORD
conn = get_db_connection()
cursor = conn.cursor()
hashed = bcrypt.hashpw(DEVELOPER_PASSWORD.encode(), bcrypt.gensalt()).decode()
cursor.execute("INSERT INTO users (username, password, premium_until) VALUES (%s, %s, NOW() + INTERVAL '9999 days') ON CONFLICT DO NOTHING", (DEVELOPER_USERNAME, hashed))
conn.commit()
cursor.close()
conn.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
