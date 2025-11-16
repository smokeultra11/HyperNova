import os
import asyncio
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from dotenv import load_dotenv

from models import db, User, Chat, DEVELOPER_USERNAME, DEVELOPER_PASSWORD_HASH
from routes import create_auth_bp, create_chat_bp, create_admin_bp
from utils import logger, init_admin_user

load_dotenv()

app = Flask(__name__, static_folder='static')

# Temel ayarlar
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✔ SQLAlchemy psycopg3 ile kendi pool’unu kullanır
# ConnectionPool KULLANAMAZSIN → hata veriyordu
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_size": 5,
    "max_overflow": 10,
    "pool_pre_ping": True
}

# Session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 gün

# CORS ve DB
CORS(app)
db.init_app(app)
Session(app)

# Rate limit
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

# Blueprint
auth_bp = create_auth_bp()
chat_bp = create_chat_bp(limiter)
admin_bp = create_admin_bp()

app.register_blueprint(auth_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(admin_bp)

# Routes
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Sunucu Hatası: {error}")
    return jsonify({"error": "Dahili Sunucu Hatası"}), 500

# Uygulama başlatılırken DB oluştur
with app.app_context():
    db.create_all()
    init_admin_user(db, DEVELOPER_USERNAME, DEVELOPER_PASSWORD_HASH)
    logger.info("Uygulama başlatıldı.")

# Local çalıştırma
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
