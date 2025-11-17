import os
import logging
import bcrypt
from flask import Flask, request, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database import init_db
from auth import auth_bp
from chat import chat_bp
from admin import admin_bp
from config import UI_TRANSLATIONS, DEVELOPER_USERNAME, DEVELOPER_PASSWORD, DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(chat_bp, url_prefix='/api')
app.register_blueprint(admin_bp)

init_db()

# Developer user ekle
from database import get_db_connection
conn = get_db_connection()
with conn.cursor() as cursor:
    cursor.execute("SELECT id FROM users WHERE username = %s", (DEVELOPER_USERNAME,))
    if not cursor.fetchone():
        hashed = bcrypt.hashpw(DEVELOPER_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("""
            INSERT INTO users (username, password, premium_until)
            VALUES (%s, %s, NOW() + INTERVAL '9999 days')
        """, (DEVELOPER_USERNAME, hashed))
        conn.commit()
        logger.info(f"Developer user '{DEVELOPER_USERNAME}' eklendi.")
conn.close()

@app.route('/')
def index():
    lang = request.cookies.get('lang', 'en')
    translations = UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['en'])
    # Orijinal HTML template'ini buraya kopyala (uzun diye kısalttım – orijinal mesajından al)
    html_template = """
    <!DOCTYPE html>
    <html lang="{{ lang }}">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Cosmic Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            /* Orijinal CSS'in tamamını buraya yapıştır – :root, body, sidebar, chat-container, message, vs. */
            :root { --bg-color: #f0f2f5; --card-bg: #ffffff; --text-color: #1f2937; /* ... tam CSS */ }
            /* Tam CSS'i orijinal kodundan kopyala */
        </style>
    </head>
    <body>
        <div id="authModal" class="modal">
            <!-- Orijinal modal HTML -->
        </div>
        <div class="main-container">
            <div class="sidebar" id="sidebar">
                <!-- Sidebar HTML -->
            </div>
            <div class="chat-wrapper">
                <div class="chat-container">
                    <!-- Header, auth-status, persona-select, chat-history, input-area -->
                </div>
            </div>
        </div>
        <script>
            const TRANSLATIONS = {{ translations | tojson }};
            // Orijinal JS'in tamamını buraya yapıştır – conversation = [], sendMessage, vs.
            let conversation = [];
            // ... tam JS
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, lang=lang, translations=translations)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
