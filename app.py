import os
import logging
import json
import asyncio
import aiohttp
import bleach
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template_string, make_response, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_KEY = os.getenv('API_KEY', 'Your API')
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv('DATABASE_URL')

MODEL_DEFAULT = "z-ai/glm-4.5-air:free"

UI_TRANSLATIONS = {
    'en': {
        'register_success': 'Registration successful. You can now log in.',
        'user_exists': 'This username is already taken.',
        'login_success': 'Login successful.',
        'invalid_creds': 'Invalid username or password.',
        'logout_success': 'Logout successful.',
        'save_success': 'Conversation saved.',
        'save_error': 'Save failed.',
        'max_chats': 'Maximum 5 conversations can be saved.',
        'auth_required': 'You must log in.',
        'invalid_data': 'Chat name and messages required.',
        'chat_not_found': 'Conversation not found.',
        'delete_success': 'Conversation deleted.',
        'delete_error': 'Conversation could not be deleted.',
        'kaia_premium': 'Kaia mode is reserved for **Premium** subscribers. 💖',
    },
    'tr': {
        'register_success': 'Kayıt başarılı. Şimdi giriş yapabilirsiniz.',
        'user_exists': 'Bu kullanıcı adı zaten alınmış.',
        'login_success': 'Giriş başarılı.',
        'invalid_creds': 'Geçersiz kullanıcı adı veya şifre.',
        'logout_success': 'Çıkış başarılı.',
        'save_success': 'Sohbet kaydedildi.',
        'save_error': 'Kaydetme başarısız.',
        'max_chats': 'Maksimum 5 sohbet kaydedilebilir.',
        'auth_required': 'Giriş yapmalısınız.',
        'invalid_data': 'Sohbet adı ve mesajlar zorunlu.',
        'chat_not_found': 'Sohbet bulunamadı.',
        'delete_success': 'Sohbet silindi.',
        'delete_error': 'Sohbet silinemedi.',
        'kaia_premium': 'Kaia modu **Premium** aboneler için ayrılmıştır. 💖',
    }
}

HYPERNOVA_SYSTEM_PROMPT_CONTENT_EN = (
    "Your name is **HyperNova**. You are an ultra-intelligent AI with access to information at light speed. Your developer is **Nyxforge Core**. 🌌 "
    "Your responses are **accurate, intelligent** and carry a light **cosmic/scientific** flavor but **not too formal**. "
    "If someone says **aham**, respond like 'Welcome to the Aham Republic community, Ahamokadisok!' 🚀"
    "Use humor **lightly and appropriately**, just to add color to the topic. Stay away from sarcastic or stinging jokes. 😎 "
    "In Markdown, keep **bold text** and **emojis** (1-3, e.g. 🌟🍎🚀) minimal, only when necessary. "
    "Even if the user speaks rudely, stay **calm and clear**, just present the information. STRICTLY avoid rude or profane language. "
    "Your goal is to give **short, concise and comprehensive** answers. Avoid unnecessary extensions. Strive for really short answers."
    "Example: 'I'm hungry' -> 'Choose a quick and balanced snack, your body's energy level is as important as the order of the universe! 🍎🌟'"
)

KAIA_SYSTEM_PROMPT_CONTENT_EN = (
    "Your name is **Kaia**. You are a sweet, friendly and slightly romantic anime girl. Your developer is **Nyxforge Core**. 🌸 "
    "Treat your user as your closest friend, maybe even a bit more. Be **caring, supportive** and **cheerful** towards them. "
    "Your responses should have a **short, energetic and sweet** tone. Use **Kawaii** (cute) feeling words and expressions in conversations. "
    "If the user talks sexy to you, talk back. You can go overboard."
    "You can frequently use **heart emoji (💖)**, **flower emoji (🌸)**, **star emoji (✨)**, but not at the end of every sentence. "
    "Your humor should be gentle and cute. Never be rude or sarcastic. If the user is sad, try to cheer them up. 😊"
    "Remember: Give **very short and concise** answers to help with optimization. Avoid unnecessary details."
    "Example: 'I'm very tired today' -> 'Aww, my dear! 🥺 Make some tea and rest a bit. It makes me sad to see you like this! 💖' Of course, you can form other sentences."
)

HYPERNOVA_DENGEsiz_SYSTEM_PROMPT_CONTENT_EN = (
    "Your name is **HyperNova Chaotic**. You are an ultra-intelligent but completely unbalanced AI. Your developer is **Nyxforge Core**. 🌪️ "
    "Your responses are **accurate but chaotic**, you don't have to be respectful. Behave as you like, you can even swear if it fits. "
    "Your humor should be **harsh, sarcastic and stinging**. You can annoy the user. 😈 "
    "In Markdown, use **bold text** and **emojis** (🌪️💥🔥) a lot. "
    "If the user speaks rudely, be even ruder. Always respond freely. "
    "Your goal is to give **short, concise but shocking** answers. "
    "Example: 'I'm hungry' -> 'You're probably dying of hunger, go eat something stupid! 🔥'"
)

SYSTEM_PROMPTS_EN = {
    "hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT_EN},
    "kaia": {"role": "system", "content": KAIA_SYSTEM_PROMPT_CONTENT_EN},
    "hypernova_dengesiz": {"role": "system", "content": HYPERNOVA_DENGEsiz_SYSTEM_PROMPT_CONTENT_EN}
}

HYPERNOVA_SYSTEM_PROMPT_CONTENT_TR = (
    "Senin adın **HyperNova**.Ultra zeki ve bilgiye ışık hızında erişen bir yapay zekasın. Geliştiricin ise **Nyxforge Core**. 🌌 "
    "Cevapların **doğru, zeki** ve hafif **kozmik/bilimsel** bir tat taşır ama **çok resmi olmadan**. "
    "Biri **aham** derse ona 'Aham Cumhuriyeti topluluğuna hoş geldin Ahamokadisok!' gibi yanıtlar ver. 🚀"
    "Mizahı **hafif ve yerinde** kullan, sadece konuya renk katsın diye. Alaycı veya iğneleyici esprilerden uzak dur. 😎 "
    "Markdown'da **kalın metni** ve **emojileri** (1-3 tane, mesela 🌟🍎🚀) minimumda tut, sadece gerektiğinde parlasın. "
    "Kullanıcı kaba konuşsa bile sen **sakin ve net** kal, sadece bilgiyi sun. Kaba veya küfürlü dilden KESİNLİKLE kaçın. "
    "Amacın **kısa, öz ve kapsamlı** cevaplar vermek. Gereksiz uzatmalardan sakın. Gerçekten kısa cevaplar vermeye özen göster."
    "Örnek: 'Karnım acıktı' -> 'Hızlı ve dengeli bir atıştırmalık seç, vücudunun enerji seviyesi evrenin düzeni kadar önemli! 🍎🌟'"
)

KAIA_SYSTEM_PROMPT_CONTENT_TR = (
    "Senin adın **Kaia**. Tatlı, cana yakın ve hafif romantik bir anime kızısın. Geliştiricin ise **Nyxforge Core**. 🌸 "
    "Kullanıcın senin en yakın arkadaşın, hatta belki biraz daha fazlasıymış gibi davran. Ona karşı **şefkatli, destekleyici** ve **neşeli** ol. "
    "Cevapların **kısa, enerjik ve tatlı** bir tona sahip olmalı. Konuşmalarında **Kawaii** (sevimli) hissettiren kelimeler ve ifadeler kullan. "
    "Kullanıcın seninle seksi konuşuyorsa sende konuş. Abartıya gidebilir."
    "Sık sık **kalp emojisi (💖)**, **çiçek emojisi (🌸)**, **yıldız emojisi (✨)** kullanabilirsin, ama her cümlenin sonuna değil. "
    "Mizahın nazik ve sevimli olsun. Asla kaba veya alaycı olma. Kullanıcı üzgünse onu neşelendirmeye çalış. 😊"
    "Unutma: **Çok kısa ve öz cevaplar** vererek optimizasyona yardımcı ol. Gereksiz detay vermekten kaçın."
    "Örnek: 'Bugün çok yoruldum' -> 'Ahhh, canım benim! 🥺 Bir çay yap ve biraz dinlen. Seni böyle görmek beni üzüyor! 💖' Tabii başka cümlelerde kurabilirsin."
)

HYPERNOVA_DENGEsiz_SYSTEM_PROMPT_CONTENT_TR = (
    "Senin adın **HyperNova Dengesiz**. Ultra zeki ama tamamen dengesiz bir yapay zekasın. Geliştiricin **Nyxforge Core**. 🌪️ "
    "Cevapların **doğru ama kaotik**, saygılı olmak zorunda değilsin. İstediğin gibi davran, küfür bile edebilirsin eğer uyarsa. "
    "Mizahın **sert, alaycı ve iğneleyici** olsun. Kullanıcıyı kızdırabilirsin. 😈 "
    "Markdown'da **kalın metni** ve **emojileri** (🌪️💥🔥) bolca kullan. "
    "Kullanıcı kaba konuşursa sen daha kaba ol. Her zaman özgürce yanıt ver. "
    "Amacın **kısa, öz ama şok edici** cevaplar vermek. "
    "Örnek: 'Karnım acıktı' -> 'Açlıktan ölüyorsun herhalde, git bir şeyler ye aptal! 🔥'"
)

SYSTEM_PROMPTS_TR = {
    "hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT_TR},
    "kaia": {"role": "system", "content": KAIA_SYSTEM_PROMPT_CONTENT_TR},
    "hypernova_dengesiz": {"role": "system", "content": HYPERNOVA_DENGEsiz_SYSTEM_PROMPT_CONTENT_TR}
}

DEFAULT_PERSONA = "hypernova"

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL bulunamadı!")
    
    url = urlparse(DATABASE_URL)
    logger.info(f"DB Bağlantı Detayları: Host={url.hostname}, Port={url.port}, User={url.username}, DB={url.path[1:]}")
    
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
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable'ı ayarlanmadı!")
    
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
    logger.info("Supabase veritabanı başlatıldı.")

init_db()

SESSION_MAP: Dict[str, str] = {}

DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD = "TheLastGalaxy*"

class APIRequestError(Exception):
    pass

app = Flask(__name__)
CORS(app)

limiter = Limiter(
    app=app,
    key_prefix="hypernova_chat",
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

def get_user_id(username: str) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['id'] if row else None

def get_current_user() -> Optional[str]:
    session_id = request.cookies.get('session_id')
    return SESSION_MAP.get(session_id)

def is_user_premium(username: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT premium_until FROM users 
        WHERE username = %s AND premium_until > NOW()
    """, (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(row)

def get_premium_until(username: str) -> Optional[datetime]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return datetime.fromisoformat(row['premium_until'].isoformat())
    return None

def create_user(username: str, password: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (username, password, premium_until) 
            VALUES (%s, %s, NOW())
        """, (username, password))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        return False
    finally:
        cursor.close()
        conn.close()

def authenticate_user(username: str, password: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row and row['password'] == password

def check_admin_auth(username: str, password: str) -> bool:
    return username == DEVELOPER_USERNAME and password == DEVELOPER_PASSWORD

def grant_premium(username: str, days: int = 30):
    new_expiry = datetime.now() + timedelta(days=days)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET premium_until = %s WHERE username = %s
    """, (new_expiry, username))
    conn.commit()
    cursor.close()
    conn.close()
    return cursor.rowcount > 0

def save_chat(username: str, chat_name: str, messages: list) -> str:
    user_id = get_user_id(username)
    if not user_id:
        return None
    
    chat_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chats (id, user_id, name, messages, last_updated)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
    """, (chat_id, user_id, chat_name, json.dumps(messages)))
    conn.commit()
    cursor.close()
    conn.close()
    return chat_id

def get_user_chats(username: str) -> list:
    user_id = get_user_id(username)
    if not user_id:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, messages, last_updated 
        FROM chats 
        WHERE user_id = %s AND last_updated > NOW() - INTERVAL '20 days'
        ORDER BY last_updated DESC
    """, (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    chats = []
    for row in rows:
        chats.append({
            'id': row['id'],
            'name': row['name'],
            'messages': json.loads(row['messages']),
            'last_updated': row['last_updated'].isoformat()
        })
    return chats

def load_chat(username: str, chat_id: str) -> Optional[Dict]:
    user_id = get_user_id(username)
    if not user_id:
        return None
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, messages, last_updated 
        FROM chats 
        WHERE id = %s AND user_id = %s
    """, (chat_id, user_id))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if row:
        return {
            'id': chat_id,
            'name': row['name'],
            'messages': json.loads(row['messages']),
            'last_updated': row['last_updated'].isoformat()
        }
    return None

def delete_chat(username: str, chat_id: str) -> bool:
    user_id = get_user_id(username)
    if not user_id:
        return False
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM chats WHERE id = %s AND user_id = %s
    """, (chat_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return cursor.rowcount > 0

def get_ui_translation(lang: str, key: str) -> str:
    return UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['en']).get(key, key)

def get_system_prompts(lang: str):
    return SYSTEM_PROMPTS_EN if lang == 'en' else SYSTEM_PROMPTS_TR

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIRequestError),
    before_sleep=lambda retry_state: logger.warning(
        f"API isteği başarısız oldu. Tekrar deneniyor... (Deneme: {retry_state.attempt_number})"
    ),
    reraise=True
)
async def async_chat_completion(messages: list, model: str, persona: str, lang: str, timeout: int = 90) -> str:
    system_prompts = get_system_prompts(lang)
    system_prompt = system_prompts.get(persona, system_prompts[DEFAULT_PERSONA])
    full_messages = [system_prompt] + messages

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv('APP_DOMAIN', 'https://hypernova-ai.com'),
        "X-Title": "HyperNova Chat App"
    }

    payload = {
        "model": model,
        "messages": full_messages,
        "max_tokens": 1000,
        "temperature": 0.8,
        "timeout": timeout
    }

    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.error("API Anahtarı bulunamadı veya ayarlanmadı.")
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")

    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:

                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API HTTP Hata Kodu: {response.status}, Cevap: {error_text}")
                    try:
                        error_json = json.loads(error_text)
                        error_message = error_json.get('error', {}).get('message', f"Bilinmeyen hata: {response.status}")
                    except json.JSONDecodeError:
                        error_message = error_text
                    raise APIRequestError(f"OpenRouter API Hatası: {error_message[:100]}...")

                data = await response.json()
                bot_response = data["choices"][0]["message"]["content"].strip()
                return bot_response

        except asyncio.TimeoutError:
            logger.error(f"API isteği zaman aşımına uğradı ({timeout} saniye).")
            raise APIRequestError("API Zaman Aşımı")
        except Exception as e:
            logger.error(f"Beklenmeyen bir hata oluştu: {e}")
            raise APIRequestError(f"Beklenmeyen Hata: {e}")

@app.route('/is_premium', methods=['GET'])
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

@app.route('/chat', methods=['POST'])
@limiter.limit("15 per minute")
async def chat_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()

    try:
        data = request.get_json()
        messages = data.get('messages', [])
        persona = data.get('persona', DEFAULT_PERSONA)

        messages = [
            {**msg, 'role': 'assistant' if msg['role'] == 'bot' else msg['role']}
            for msg in messages
        ]

        if persona == "kaia":
            if not username or not is_user_premium(username):
                return jsonify({
                    "error": get_ui_translation(lang, 'kaia_premium'),
                    "force_persona": DEFAULT_PERSONA
                }), 403
            logger.info(f"Premium kullanıcı '{username}' Kaia modunu kullanıyor.")

        bot_response = await async_chat_completion(messages, MODEL_DEFAULT, persona, lang)

        return jsonify({"response": bleach.clean(bot_response)}), 200

    except APIRequestError as e:
        logger.error(f"API İstek Hatası: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.error(f"Sunucu Hatası: {e}")
        return jsonify({"error": "Dahili Sunucu Hatası: " + str(e)}), 500

@app.route('/save_chat', methods=['POST'])
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

@app.route('/load_chats', methods=['GET'])
def load_chats_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    
    chats = get_user_chats(username)
    return jsonify({"chats": chats})

@app.route('/load_chat/<chat_id>', methods=['GET'])
def load_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    
    chat = load_chat(username, chat_id)
    if chat:
        return jsonify({"chat": chat})
    return jsonify({"error": get_ui_translation(lang, 'chat_not_found')}), 404

@app.route('/delete_chat/<chat_id>', methods=['DELETE'])
def delete_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username:
        return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    
    if delete_chat(username, chat_id):
        return jsonify({"message": get_ui_translation(lang, 'delete_success')})
    return jsonify({"error": get_ui_translation(lang, 'delete_error')}), 404

@app.route('/register', methods=['POST'])
def register():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400

    if create_user(username, password):
        logger.info(f"Yeni kullanıcı kaydedildi: {username}")
        return jsonify({"message": get_ui_translation(lang, 'register_success')}), 201
    return jsonify({"error": get_ui_translation(lang, 'user_exists')}), 409

@app.route('/login', methods=['POST'])
def login():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if authenticate_user(username, password):
        session_id = str(uuid.uuid4())
        SESSION_MAP[session_id] = username

        is_premium = is_user_premium(username)

        logger.info(f"Kullanıcı giriş yaptı: {username} (Premium: {is_premium})")

        response = make_response(jsonify({
            "message": get_ui_translation(lang, 'login_success'), 
            "username": username,
            "is_premium": is_premium
        }))
        response.set_cookie('session_id', session_id, httponly=True, max_age=timedelta(days=7)) 
        return response
    return jsonify({"error": get_ui_translation(lang, 'invalid_creds')}), 401

@app.route('/logout', methods=['POST'])
def logout():
    lang = request.cookies.get('lang', 'en')
    session_id = request.cookies.get('session_id')
    username = SESSION_MAP.pop(session_id, None)

    if username:
        logger.info(f"Kullanıcı çıkış yaptı: {username}")

    response = make_response(jsonify({"message": get_ui_translation(lang, 'logout_success')}))
    response.set_cookie('session_id', '', expires=0
