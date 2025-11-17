from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template_string
from models import db, User, Chat, DEVELOPER_USERNAME, DEVELOPER_PASSWORD_HASH
from utils import async_chat_completion, get_system_prompts, get_ui_translation, logger, API_KEY, MODEL_DEFAULT
import bleach
import asyncio
import json
from datetime import datetime, timedelta
import uuid
from werkzeug.security import check_password_hash  # Admin için

# Blueprint oluşturma fonksiyonları (döngü kırıcı)
def create_auth_bp():
    auth_bp = Blueprint('auth', __name__)

    @auth_bp.route('/register', methods=['POST'])
    def register():
        lang = request.cookies.get('lang', 'en')
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({"error": get_ui_translation(lang, 'user_exists')}), 409
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info(f"Yeni kullanıcı: {username}")
        return jsonify({"message": get_ui_translation(lang, 'register_success')}), 201

    @auth_bp.route('/login', methods=['POST'])
    def login():
        lang = request.cookies.get('lang', 'en')
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            logger.info(f"Giriş: {username} (Premium: {user.is_premium()})")
            return jsonify({
                "message": get_ui_translation(lang, 'login_success'),
                "username": username,
                "is_premium": user.is_premium()
            })
        return jsonify({"error": get_ui_translation(lang, 'invalid_creds')}), 401

    @auth_bp.route('/logout', methods=['POST'])
    def logout():
        lang = request.cookies.get('lang', 'en')
        session.pop('user_id', None)
        return jsonify({"message": get_ui_translation(lang, 'logout_success')})

    @auth_bp.route('/is_premium', methods=['GET'])
    def is_premium():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"logged_in": False})
        user = User.query.get(user_id)
        return jsonify({
            "logged_in": True,
            "username": user.username,
            "is_premium": user.is_premium(),
            "premium_until": user.premium_until.isoformat() if user.is_premium() else None
        })

    return auth_bp

def create_chat_bp(limiter):  # Limiter parametresi al
    chat_bp = Blueprint('chat', __name__)

    @chat_bp.route('/chat', methods=['POST'])
    @limiter.limit("15 per minute")  # Artık limiter mevcut
    def chat_endpoint():
        lang = request.cookies.get('lang', 'en')
        user_id = session.get('user_id')
        data = request.get_json()
        messages = data.get('messages', [])
        persona = data.get('persona', 'hypernova')

        if persona == 'kaia' and (not user_id or not User.query.get(user_id).is_premium()):
            return jsonify({"error": get_ui_translation(lang, 'kaia_premium'), "force_persona": 'hypernova'}), 403

        messages = [{"role": "user" if m.get('role') == 'user' else "assistant", "content": m.get('content')} for m in messages]
        system_prompts = get_system_prompts(lang)
        full_messages = [system_prompts.get(persona, system_prompts['hypernova'])] + messages

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot_response = loop.run_until_complete(async_chat_completion(full_messages, MODEL_DEFAULT, persona, lang))
        loop.close()

        return jsonify({"response": bleach.clean(bot_response)})

    @chat_bp.route('/save_chat', methods=['POST'])
    def save_chat():
        lang = request.cookies.get('lang', 'en')
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
        data = request.get_json()
        chat_name = data.get('name')
        messages = json.dumps(data.get('messages', []))
        if not chat_name or not messages:
            return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400

        if Chat.query.filter_by(user_id=user_id).count() >= 5:
            return jsonify({"error": get_ui_translation(lang, 'max_chats')}), 400

        chat_id = str(uuid.uuid4())
        chat = Chat(id=chat_id, user_id=user_id, name=chat_name, messages=messages)
        db.session.add(chat)
        db.session.commit()
        return jsonify({"message": get_ui_translation(lang, 'save_success'), "chat_id": chat_id}), 201

    @chat_bp.route('/load_chats', methods=['GET'])
    def load_chats():
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Auth required"}), 401
        chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.last_updated.desc()).all()
        return jsonify({"chats": [c.to_dict() for c in chats]})

    @chat_bp.route('/load_chat/<chat_id>', methods=['GET'])
    def load_chat(chat_id):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Auth required"}), 401
        chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
        if not chat:
            return jsonify({"error": "Chat not found"}), 404
        return jsonify({"chat": chat.to_dict()})

    @chat_bp.route('/delete_chat/<chat_id>', methods=['DELETE'])
    def delete_chat(chat_id):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Auth required"}), 401
        chat = Chat.query.filter_by(id=chat_id, user_id=user_id).first()
        if not chat:
            return jsonify({"error": "Not found"}), 404
        db.session.delete(chat)
        db.session.commit()
        return jsonify({"message": "Deleted"})

    return chat_bp

def create_admin_bp():
    admin_bp = Blueprint('admin', __name__)

    ADMIN_LOGIN_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="tr">
    <head><title>Admin Giriş</title><style>body{background:#f0f0f0;display:flex;justify-content:center;align-items:center;height:100vh;}form{background:white;padding:20px;border-radius:10px;}</style></head>
    <body><form method="POST"><input name="username" placeholder="Username"><input type="password" name="password" placeholder="Password"><button>Giriş</button></form></body>
    </html>
    """

    ADMIN_PANEL_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="tr">
    <head><title>Admin Panel</title><style>body{background:#1a1a1a;color:white;padding:20px;}table{border-collapse:collapse;}th,td{border:1px solid #333;padding:10px;}</style></head>
    <body><h1>Admin Panel</h1><p>{message}</p><form method="POST"><input name="target_username" placeholder="Username for Premium"><button name="grant">Grant 30 Days Premium</button></form><table><tr><th>Username</th><th>Status</th><th>Premium Until</th></tr>{user_list}</table></body>
    </html>
    """

    @admin_bp.route('/', methods=['GET', 'POST'])
    def admin_panel():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if username == DEVELOPER_USERNAME and check_password_hash(DEVELOPER_PASSWORD_HASH, password):
                session['admin'] = True
                return redirect(url_for('admin_panel'))
            return render_template_string(ADMIN_LOGIN_TEMPLATE), 401

        if not session.get('admin'):
            return render_template_string(ADMIN_LOGIN_TEMPLATE)

        message = ""
        if request.form.get('grant'):
            target_username = request.form.get('target_username')
            user = User.query.filter_by(username=target_username).first()
            if user:
                user.premium_until = datetime.utcnow() + timedelta(days=30)
                db.session.commit()
                message = f"Premium granted to {target_username} until {user.premium_until.strftime('%Y-%m-%d')}"

        users = User.query.all()
        user_list = ''.join(f"<tr><td>{u.username}</td><td>{'Premium' if u.is_premium() else 'Free'}</td><td>{u.premium_until.strftime('%Y-%m-%d')}</td></tr>" for u in users)
        return render_template_string(ADMIN_PANEL_TEMPLATE.format(message=message, user_list=user_list))

    return admin_bp
