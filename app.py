import os
import logging
from flask import Flask, render_template, redirect, url_for
from flask_cors import CORS
from config import init_db  # DB init
from auth import auth_bp
from chat import chat_bp
from admin import admin_bp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Blueprints register
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(chat_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/')

# DB init
init_db()

@app.route('/')
def index():
    lang = request.cookies.get('lang', 'en')
    # Translations'ı template'e geç
    translations = UI_TRANSLATIONS[lang]  # Config'den
    return render_template('index.html', lang=lang, translations=translations)

# Admin için
@app.route('/admin')
def admin_redirect():
    return redirect(url_for('admin.admin_panel'))

if __name__ == '__main__':
    # Developer user ekle (database.py'de)
    app.run(debug=True, host='0.0.0.0', port=5000)
