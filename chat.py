from flask import Blueprint, request, jsonify
import asyncio
from aiohttp import ClientSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import API_KEY, API_URL, MODEL_DEFAULT, get_system_prompts
from database import get_current_user, is_user_premium, save_chat, get_user_chats, load_chat, delete_chat
import bleach
import json
import logging

chat_bp = Blueprint('chat', __name__)
logger = logging.getLogger(__name__)

class APIRequestError(Exception):
    pass

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(APIRequestError))
async def async_chat_completion(messages, model, persona, lang):
    # Aynı async fonksiyon, system prompt ekle
    pass  # Orijinal kod

@chat_bp.route('/chat', methods=['POST'])
async def chat():
    # Aynı endpoint, premium check ile
    pass

@chat_bp.route('/save_chat', methods=['POST'])
def save_chat_endpoint():
    # Aynı

# load_chats, load_chat/<id>, delete_chat/<id> endpoint'leri...
