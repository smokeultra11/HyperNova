from flask import Blueprint, request, jsonify
from database import get_current_user, is_user_premium, save_chat, get_user_chats, load_chat, delete_chat
from config import get_ui_translation, DEFAULT_PERSONA
from utils import async_chat_completion, APIRequestError
import asyncio
import logging

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat', methods=['POST'])
async def chat_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    data = request.get_json()
    messages = data.get('messages', [])
    persona = data.get('persona', DEFAULT_PERSONA)
    messages = [
        {**msg, 'role': 'assistant' if msg['role'] == 'bot' else msg['role']}
        for msg in messages
    ]
    if persona == "kaia" and (not username or not is_user_premium(username)):
        return jsonify({
            "error": get_ui_translation(lang, 'kaia_premium'),
            "force_persona": DEFAULT_PERSONA
        }), 403
    try:
        bot_response = await async_chat_completion(messages, MODEL_DEFAULT, persona, lang)
        return jsonify({"response": bleach.clean(bot_response)})
    except APIRequestError as e:
        logger.error(f"API Hata: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.error(f"Sunucu Hata: {e}")
        return jsonify({"error": "Dahili Hata"}), 500

@chat_bp.route('/save_chat', methods=['POST'])
def save_chat_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    data = request.get_json()
    chat_name = data.get('name')
    messages = data.get('messages', [])
    if not chat_name or not messages:
        return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400
    user_chats = get_user_chats(username)
    if len(user_chats) >= 5:
        return jsonify({"error": get_ui_translation(lang, 'max_chats')}), 400
    chat_id = save_chat(username, chat_name, messages)
    if chat_id:
        return jsonify({"message": get_ui_translation(lang, 'save_success'), "chat_id": chat_id}), 201
    return jsonify({"error": get_ui_translation(lang, 'save_error')}), 500

@chat_bp.route('/load_chats', methods=['GET'])
def load_chats_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    chats = get_user_chats(username)
    return jsonify({"chats": chats})

@chat_bp.route('/load_chat/<chat_id>', methods=['GET'])
def load_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    chat = load_chat(username, chat_id)
    if chat:
        return jsonify({"chat": chat})
    return jsonify({"error": get_ui_translation(lang, 'chat_not_found')}), 404

@chat_bp.route('/delete_chat/<chat_id>', methods=['DELETE'])
def delete_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    if delete_chat(username, chat_id):
        return jsonify({"message": get_ui_translation(lang, 'delete_success')})
    return jsonify({"error": get_ui_translation(lang, 'delete_error')}), 404
