from flask import Blueprint, request, jsonify, make_response
from flask_limiter.util import get_remote_address
from flask_limiter import Limiter
from database import authenticate_user, create_user, is_user_premium, get_premium_until, SESSION_MAP
from config import get_ui_translation, UI_TRANSLATIONS, SESSION_LIFETIME
import uuid
import logging

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)
limiter = Limiter(key_func=get_remote_address, default_limits=["60 per hour", "15 per minute"])

@auth_bp.route('/register', methods=['POST'])
def register():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400
    if create_user(username, password):
        logger.info(f"Yeni kullanıcı: {username}")
        return jsonify({"message": get_ui_translation(lang, 'register_success')}), 201
    return jsonify({"error": get_ui_translation(lang, 'user_exists')}), 409

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if authenticate_user(username, password):
        session_id = str(uuid.uuid4())
        SESSION_MAP[session_id] = username
        is_premium = is_user_premium(username)
        logger.info(f"Giriş: {username} (Premium: {is_premium})")
        response = make_response(jsonify({
            "message": get_ui_translation(lang, 'login_success'),
            "username": username,
            "is_premium": is_premium
        }))
        response.set_cookie('session_id', session_id, httponly=True, max_age=SESSION_LIFETIME)
        return response
    return jsonify({"error": get_ui_translation(lang, 'invalid_creds')}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    lang = request.cookies.get('lang', 'en')
    session_id = request.cookies.get('session_id')
    username = SESSION_MAP.pop(session_id, None)
    if username:
        logger.info(f"Çıkış: {username}")
    response = make_response(jsonify({"message": get_ui_translation(lang, 'logout_success')}))
    response.set_cookie('session_id', '', expires=0)
    return response

@auth_bp.route('/is_premium', methods=['GET'])
def is_premium_endpoint():
    username = get_current_user()
    is_premium = False
    premium_until_str = None
    if username:
        is_premium = is_user_premium(username)
        premium_until = get_premium_until(username)
        if is_premium and premium_until:
            premium_until_str = premium_until.strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({
        "logged_in": bool(username),
        "username": username,
        "is_premium": is_premium,
        "premium_until": premium_until_str
    })
