from flask import Blueprint, request, jsonify, make_response
from flask_limiter import Limiter
from database import authenticate_user, create_user, get_current_user
from config import UI_TRANSLATIONS, SESSION_MAP
import uuid
from datetime import timedelta

auth_bp = Blueprint('auth', __name__)
limiter = Limiter(key_func=lambda: get_remote_address())

@auth_bp.route('/register', methods=['POST'])
def register():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if create_user(username, password):
        return jsonify({"message": UI_TRANSLATIONS[lang]['register_success']}), 201
    return jsonify({"error": UI_TRANSLATIONS[lang]['user_exists']}), 409

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    # Aynı kod, ama bcrypt ile authenticate_user çağır
    # Session cookie set et
    pass  # Tam implementasyon orijinalden kopyala

@auth_bp.route('/logout', methods=['POST'])
def logout():
    # Aynı

@auth_bp.route('/is_premium', methods=['GET'])
def is_premium():
    # Aynı
