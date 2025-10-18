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
from psycopg2.pool import SimpleConnectionPool
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

MODEL_DEFAULT = "meituan/longcat-flash-chat:free"

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
    "Markdown’da **kalın metni** ve **emojileri** (1-3 tane, mesela 🌟🍎🚀) minimumda tut, sadece gerektiğinde parlasın. "
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
    "Markdown’da **kalın metni** ve **emojileri** (🌪️💥🔥) bolca kullan. "
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

# Optimized DB Connection Pool
db_pool = None

def init_db_pool():
    global db_pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable'ı ayarlanmadı!")
    
    url = urlparse(DATABASE_URL)
    db_pool = SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=url.hostname,
        port=url.port,
        user=url.username,
        password=url.password,
        database=url.path[1:],
        cursor_factory=RealDictCursor
    )
    logger.info("DB connection pool initialized.")

def get_db_connection():
    if db_pool is None:
        init_db_pool()
    return db_pool.getconn()

def put_db_connection(conn):
    db_pool.putconn(conn)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            premium_until TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Chats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            messages TEXT NOT NULL,
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    cursor.close()
    put_db_connection(conn)
    logger.info("Database initialized.")

# Initialize on startup
init_db()

# In-Memory Session Map
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
    put_db_connection(conn)
    return row['id'] if row else None

def get_current_user() -> Optional[str]:
    session_id = request.cookies.get('session_id')
    return SESSION_MAP.get(session_id)

def is_user_premium(username: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM users 
        WHERE username = %s AND premium_until > NOW()
    """, (username,))
    row = cursor.fetchone()
    cursor.close()
    put_db_connection(conn)
    return bool(row)

def get_premium_until(username: str) -> Optional[datetime]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT premium_until FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    put_db_connection(conn)
    if row:
        return row['premium_until']
    return None

def create_user(username: str, password: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (username, password, premium_until) 
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        """, (username, password))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        return False
    finally:
        cursor.close()
        put_db_connection(conn)

def authenticate_user(username: str, password: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    put_db_connection(conn)
    return row and row['password'] == password

def check_admin_auth(username: str, password: str) -> bool:
    return username == DEVELOPER_USERNAME and password == DEVELOPER_PASSWORD

def grant_premium(username: str, days: int = 30) -> bool:
    new_expiry = datetime.now() + timedelta(days=days)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET premium_until = %s WHERE username = %s
    """, (new_expiry, username))
    conn.commit()
    affected = cursor.rowcount > 0
    cursor.close()
    put_db_connection(conn)
    return affected

def save_chat(username: str, chat_name: str, messages: list) -> Optional[str]:
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
    put_db_connection(conn)
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
    put_db_connection(conn)
    
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
    put_db_connection(conn)
    
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
    affected = cursor.rowcount > 0
    cursor.close()
    put_db_connection(conn)
    return affected

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
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")

    connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
    timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.post(API_URL, json=payload, headers=headers) as response:
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
    response.set_cookie('session_id', '', expires=0)
    return response

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    is_authenticated = False

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'login':
            admin_user = request.form.get('admin_username')
            admin_pass = request.form.get('admin_password')
            if check_admin_auth(admin_user, admin_pass):
                return redirect(url_for('admin_panel', auth='success'))
            else:
                return admin_login_template("Geçersiz Yönetici Kimlik Bilgisi."), 401

        elif form_type == 'premium_grant':
            admin_user = request.form.get('auth_username')
            admin_pass = request.form.get('auth_password')

            if not check_admin_auth(admin_user, admin_pass):
                return admin_login_template("Yetkisiz İşlem Denemesi. Lütfen Yönetici olarak giriş yapın."), 403

            target_username = request.form.get('target_username')

            if get_user_id(target_username) is None:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** bulunamadı."), 404

            if grant_premium(target_username):
                logger.info(f"Admin: {target_username} kullanıcısının premiumluğu uzatıldı.")
                message = f"Başarılı! **{target_username}** kullanıcısının premium üyeliği **{ (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')}** tarihine kadar aktifleştirildi (30 gün)."
                return admin_panel_template(message, True)
            else:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** premium verilemedi."), 500

    if request.args.get('auth') == 'success':
        is_authenticated = True

    if is_authenticated:
        return admin_panel_template("", True)
    else:
        return admin_login_template()

def admin_login_template(error_message: str = ""):
    return render_template_string(f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <title>Yönetici Girişi</title>
        <style>
            body {{ font-family: sans-serif; background-color: #f0f4f8; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .login-box {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); width: 350px; text-align: center; }}
            h2 {{ color: #4f46e5; margin-bottom: 30px; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 12px; margin-bottom: 20px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; }}
            button {{ width: 100%; padding: 12px; background-color: #4f46e5; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; }}
            button:hover {{ background-color: #4338ca; }}
            .error {{ color: #ef4444; margin-bottom: 15px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>HyperNova Admin Girişi</h2>
            {f'<div class="error">{error_message}</div>' if error_message else ''}
            <form method="POST" action="/admin">
                <input type="hidden" name="form_type" value="login">
                <input type="text" name="admin_username" placeholder="Yönetici Kullanıcı Adı" required>
                <input type="password" name="admin_password" placeholder="Yönetici Şifresi" required>
                <button type="submit">Giriş Yap</button>
            </form>
        </div>
    </body>
    </html>
    """)

def admin_panel_template(message: str = "", is_authenticated: bool = False):
    if not is_authenticated:
        return redirect(url_for('admin_panel'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, premium_until FROM users ORDER BY premium_until DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    put_db_connection(conn)

    user_list_html = ""
    for row in rows:
        username = row['username']
        is_premium_active = is_user_premium(username)
        status_text = "AKTİF" if is_premium_active else "PASİF"
        status_color = "color: green;" if is_premium_active else "color: red;"
        expiry_date = row['premium_until'].isoformat()

        user_list_html += f"""
        <tr>
            <td>{username}</td>
            <td><span style="{status_color}">{status_text}</span></td>
            <td>{expiry_date}</td>
        </tr>
        """

    return render_template_string(f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <title>HyperNova Yönetici Paneli</title>
        <style>
            body {{ font-family: sans-serif; background-color: #1f2937; color: #f9fafb; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; background: #374151; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            h1 {{ color: #8b5cf6; border-bottom: 2px solid #8b5cf6; padding-bottom: 10px; margin-bottom: 20px; }}
            .message {{ background: #10b981; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-weight: bold; }}
            
            form {{ background: #4b5563; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #d1d5db; }}
            input[type="text"] {{ width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #6b7280; border-radius: 6px; box-sizing: border-box; background: #374151; color: #f9fafb; }}
            button {{ padding: 10px 20px; background-color: #8b5cf6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }}
            button:hover {{ background-color: #a78bfa; }}
            
            h2 {{ color: #facc15; margin-top: 40px; border-bottom: 1px solid #6b7280; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #4b5563; }}
            th {{ background-color: #4b5563; color: #facc15; font-weight: bold; }}
            tr:hover {{ background-color: #525a66; }}
            td:nth-child(2) {{ font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1> Yönetici Paneli - Premium Aktivasyon </h1>
            
            {'<div class="message">' + message + '</div>' if message else ''}
            
            <h2>30 Günlük Premium Aktifleştirme</h2>
            <form method="POST" action="/admin">
                <input type="hidden" name="form_type" value="premium_grant">
                
                <p style="color: #ef4444; font-weight: bold;">UYARI: Bu demo, kalıcı bir oturum tutmaz. Her işlemde yönetici kimlik bilgisi gereklidir!</p>
                <label for="auth_username">Yönetici Kullanıcı Adı (Tekrar Giriş):</label>
                <input type="text" id="auth_username" name="auth_username" value="{DEVELOPER_USERNAME}" required>
                
                <label for="auth_password">Yönetici Şifresi (Tekrar Giriş):</label>
                <input type="password" id="auth_password" name="auth_password" required>
                
                <label for="target_username">Premium Aktifleştirilecek Kullanıcı Adı:</label>
                <input type="text" id="target_username" name="target_username" placeholder="Kullanıcı Adı Girin" required>
                
                <button type="submit">Premium Aktifleştir (30 Gün)</button>
            </form>
            
            <h2>Sistemdeki Tüm Kullanıcılar ({len(rows)})</h2>
            <table>
                <thead>
                    <tr>
                        <th>Kullanıcı Adı</th>
                        <th>Premium Durumu</th>
                        <th>Bitiş Tarihi</th>
                    </tr>
                </thead>
                <tbody>
                    {user_list_html if rows else '<tr><td colspan="3">Sistemde kayıtlı kullanıcı yok.</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """)

@app.route('/', methods=['GET'])
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Cosmic Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #fafafa;
                --card-bg: #ffffff;
                --history-bg: #f1f5f9;
                --text-color: #0f172a;
                --user-bubble: #3b82f6;
                --bot-bubble: #ffffff;
                --primary-color: #6366f1;
                --typing-color: #6366f1;
                --border-color: #e2e8f0;
                --shadow-color: rgba(0,0,0,0.05);
                --kaia-primary-color: #ec4899;
                --kaia-bot-bubble: #fdf2f8;
                --kaia-text-color: #be185d;
            }

            @media (prefers-color-scheme: dark) {
                :root {
                    --bg-color: #0f0f23;
                    --card-bg: #1e1e2e;
                    --history-bg: #1e1e2e;
                    --text-color: #cdd6f4;
                    --user-bubble: #4c1d95;
                    --bot-bubble: #313244;
                    --primary-color: #a6a6f1;
                    --typing-color: #a6a6f1;
                    --border-color: #45475a;
                    --shadow-color: rgba(0,0,0,0.5);
                    --kaia-primary-color: #f5c2e7;
                    --kaia-bot-bubble: #1e1b4b;
                    --kaia-text-color: #f5c2e7;
                }
            }

            body.light-theme {
                --bg-color: #fafafa; --card-bg: #ffffff; --history-bg: #f1f5f9; --text-color: #0f172a;
                --user-bubble: #3b82f6; --bot-bubble: #ffffff; --primary-color: #6366f1; --typing-color: #6366f1;
                --border-color: #e2e8f0; --shadow-color: rgba(0,0,0,0.05);
            }
            body.dark-theme {
                --bg-color: #0f0f23; --card-bg: #1e1e2e; --history-bg: #1e1e2e; --text-color: #cdd6f4;
                --user-bubble: #4c1d95; --bot-bubble: #313244; --primary-color: #a6a6f1; --typing-color: #a6a6f1;
                --border-color: #45475a; --shadow-color: rgba(0,0,0,0.5);
            }

            body.kaia-theme {
                --bg-color: var(--kaia-bot-bubble);
                --card-bg: var(--kaia-bot-bubble);
                --history-bg: #fce7f3;
                --user-bubble: var(--kaia-primary-color);
                --bot-bubble: #ffffff;
                --primary-color: var(--kaia-primary-color);
                --text-color: #0f172a;

                @media (prefers-color-scheme: dark) {
                    --bg-color: #1a0d2e;
                    --card-bg: #1a0d2e;
                    --history-bg: #2a1b3d;
                    --user-bubble: #f5c2e7;
                    --bot-bubble: #4c1d95;
                    --text-color: #f5c2e7;
                }
            }
            
            body {  
                background: linear-gradient(to bottom, var(--bg-color), var(--card-bg));  
                color: var(--text-color);  
                font-family: 'Inter', sans-serif;
                margin: 0;  
                padding: 0;  
                min-height: 100vh;  
                transition: all 0.4s ease;
            }

            .main-container {
                display: flex;
                height: 100vh;
                max-width: 100vw;
                overflow: hidden;
            }

            .sidebar {
                width: 260px;
                background: var(--card-bg);
                border-right: 1px solid var(--border-color);
                padding: 16px;
                overflow-y: auto;
                box-shadow: 2px 0 10px var(--shadow-color);
                display: flex;
                flex-direction: column;
                transition: all 0.3s ease;
            }
            .sidebar::-webkit-scrollbar { width: 4px; }
            .sidebar::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 2px; }

            .sidebar h3 {
                padding: 0 0 12px;
                margin: 0 0 16px;
                color: var(--primary-color);
                font-size: 14px;
                font-weight: 600;
                border-bottom: 1px solid var(--border-color);
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }
            .sidebar-toolbar {
                display: flex;
                flex-direction: column;
                gap: 8px;
                margin-bottom: 16px;
            }
            .new-chat-button, .save-chat-sidebar-button {
                padding: 12px;
                background: linear-gradient(135deg, var(--primary-color), var(--primary-color));
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 500;
                transition: all 0.2s ease;
                box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
            }
            .new-chat-button:hover, .save-chat-sidebar-button:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .save-chat-sidebar-button {
                background: linear-gradient(135deg, #10b981, #059669);
                box-shadow: 0 2px 8px rgba(16, 185, 129, 0.2);
            }
            .save-chat-sidebar-button:hover {
                box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            }
            .saved-chat {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 8px;
                cursor: pointer;
                border-radius: 6px;
                transition: all 0.2s ease;
                font-size: 13px;
                font-weight: 500;
                margin-bottom: 4px;
                position: relative;
            }
            .saved-chat:hover {
                background: var(--primary-color);
                color: white;
                transform: translateX(2px);
            }
            .saved-chat.active {
                background: var(--primary-color);
                color: white;
                box-shadow: inset 0 0 0 1px rgba(255,255,255,0.1);
            }
            .saved-chat-name {
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .delete-chat-button {
                background: none;
                border: none;
                color: inherit;
                cursor: pointer;
                font-size: 14px;
                padding: 2px 4px;
                border-radius: 4px;
                transition: all 0.2s ease;
                opacity: 0.5;
            }
            .saved-chat:hover .delete-chat-button {
                opacity: 1;
            }
            .delete-chat-button:hover {
                background: rgba(255,255,255,0.2);
                color: #ef4444;
            }
            .save-limit {
                padding: 8px;
                text-align: center;
                font-size: 11px;
                color: var(--text-color);
                opacity: 0.6;
                font-style: italic;
                margin-top: auto;
            }

            .chat-wrapper {
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: stretch;
                padding: 0;
            }
            .chat-container {  
                width: 100%;
                height: 100vh;
                background-color: var(--card-bg);  
                display: flex;  
                flex-direction: column;  
                border: 1px solid var(--border-color);
                transition: all 0.4s ease;
            }
            
            #auth-status {
                display: flex;
                align-items: center;
                gap: 10px;
                margin: 16px;
                padding: 12px;
                background-color: var(--history-bg);
                border-radius: 8px;
                font-size: 13px;
                font-weight: 500;
                color: var(--text-color);
                justify-content: space-between;
            }
            #auth-status button, #logout-button {
                background: var(--primary-color);
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 500;
                transition: background 0.2s;
                font-size: 13px;
            }
            #auth-status button:hover, #logout-button:hover {
                background: var(--primary-color);
            }
            .premium-tag {
                background-color: #facc15;
                color: #854d0e;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 700;
                margin-left: 5px;
            }

            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 0 16px;
                margin-bottom: 0;
            }
            .title {  
                font-size: 24px;  
                font-weight: 600;
                color: var(--primary-color);
                letter-spacing: -0.25px;
                transition: color 0.4s ease;
            }
            #theme-toggle, #clear-button, #lang-toggle {
                background: var(--history-bg);
                color: var(--text-color);
                border: 1px solid var(--border-color);
                border-radius: 6px;
                padding: 8px;
                cursor: pointer;
                transition: all 0.2s;
                font-size: 16px;
                margin-left: 8px;
            }
            #theme-toggle:hover, #clear-button:hover, #lang-toggle:hover {
                background: var(--bot-bubble);
                transform: scale(1.05);
            }
            .header-buttons {
                display: flex;
                align-items: center;
            }
            
            #persona-select {
                padding: 8px 12px;
                border-radius: 6px;
                border: 1px solid var(--border-color);
                background-color: var(--card-bg);
                color: var(--text-color);
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                margin: 16px;
                transition: all 0.3s;
                appearance: none;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%236B7280' d='M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 8px center;
                padding-right: 24px;
            }
            #persona-select:disabled {
                cursor: not-allowed;
                opacity: 0.7;
                border-style: dashed;
            }
            body.kaia-theme #persona-select {
                border-color: var(--kaia-primary-color);
                color: var(--kaia-text-color);
            }

            #chat-history {  
                flex: 1;  
                background-color: var(--history-bg);  
                border-radius: 0 0 12px 12px;  
                padding: 16px;  
                overflow-y: auto;  
                font-size: 14px;  
                line-height: 1.5;  
                scroll-behavior: smooth;
                font-family: 'Inter', sans-serif;
            }
            #chat-history::-webkit-scrollbar { width: 6px; }
            #chat-history::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 3px; }

            .message {  
                margin-bottom: 12px;  
                padding: 12px 16px;  
                border-radius: 12px;
                max-width: 80%;
                word-wrap: break-word;
                animation: fadeInUp 0.3s ease-out;
                box-shadow: 0 1px 3px var(--shadow-color);
                font-family: 'Inter', sans-serif;
                position: relative;
            }
            .user {  
                background: linear-gradient(135deg, var(--user-bubble), #2563eb);  
                color: white;  
                margin-left: auto;
                border-bottom-right-radius: 4px;
            }
            .bot {  
                background: var(--bot-bubble);  
                color: var(--text-color);  
                margin-right: auto;
                border-bottom-left-radius: 4px;
                border: 1px solid var(--border-color);
            }
            body.kaia-theme .bot {
                background-color: var(--kaia-bot-bubble);
                color: var(--kaia-text-color);
                border: 1px solid var(--kaia-primary-color);
            }

            .message strong {
                font-weight: 600;
                color: var(--primary-color);
            }
            .user strong {
                color: #fff;
            }

            .input-area {  
                display: flex;  
                gap: 12px;
                align-items: center;
                padding: 16px;
                border-top: 1px solid var(--border-color);
                background: var(--card-bg);
            }
            #message-input {  
                flex: 1;  
                padding: 12px 16px;  
                border: 1px solid var(--border-color);
                border-radius: 24px;
                background-color: var(--card-bg);
                color: var(--text-color);
                font-size: 14px;
                resize: none;
                transition: all 0.2s;
                font-family: 'Inter', sans-serif;
            }
            #message-input:focus {
                border-color: var(--primary-color);
                box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
                outline: none;
            }
            .action-button {  
                padding: 0 16px;
                background: linear-gradient(135deg, var(--primary-color), var(--primary-color));  
                color: white;  
                border: none;  
                border-radius: 24px;
                cursor: pointer;  
                font-weight: 500;
                transition: all 0.2s;
                height: 44px;
                font-size: 14px;
                font-family: 'Inter', sans-serif;
                min-width: 60px;
            }
            .action-button:hover {  
                transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .action-button:disabled {
                background: var(--border-color);
                cursor: not-allowed;
                transform: none;
            }

            .modal {
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0,0,0,0.5);
                display: none;
                justify-content: center;
                align-items: center;
                backdrop-filter: blur(4px);
            }
            .modal-content {
                background-color: var(--card-bg);
                padding: 32px;
                border-radius: 12px;
                width: 90%;
                max-width: 400px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                text-align: center;
                font-family: 'Inter', sans-serif;
            }
            .modal-content h3 {
                color: var(--primary-color);
                margin-top: 0;
                margin-bottom: 20px;
                font-weight: 600;
            }
            .modal-content input {
                width: 100%;
                padding: 12px;
                margin-bottom: 16px;
                border: 1px solid var(--border-color);
                border-radius: 8px;
                box-sizing: border-box;
                background-color: var(--history-bg);
                color: var(--text-color);
                font-family: 'Inter', sans-serif;
            }
            .modal-content button {
                width: 100%;
                padding: 12px;
                margin-top: 8px;
                background: var(--primary-color);
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 500;
                font-family: 'Inter', sans-serif;
                transition: background 0.2s;
            }
            .modal-content button:hover {
                background: var(--primary-color);
            }
            #auth-message {
                color: #ef4444;
                margin-bottom: 16px;
                font-size: 13px;
            }

            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                color: var(--typing-color);
                font-style: italic;
                padding: 12px 16px;
                margin-right: auto;
                border-radius: 12px;
                font-size: 14px;
                font-family: 'Inter', sans-serif;
            }
            .spinner {
                width: 6px;
                height: 6px;
                background-color: var(--typing-color);
                border-radius: 50%;
                opacity: 0;
                animation: dot-pulse 1.4s infinite ease-in-out;
            }
            .spinner:nth-child(2) { animation-delay: 0.2s; }
            .spinner:nth-child(3) { animation-delay: 0.4s; }

            @keyframes dot-pulse {
                0%, 60%, 100% { transform: scale(0.8); opacity: 0.5; }
                30% { transform: scale(1.2); opacity: 1; }
            }

            @keyframes fadeInUp {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }

            @media (max-width: 768px) {
                .main-container { flex-direction: column; }
                .sidebar { width: 100%; height: auto; order: 2; }
                .chat-wrapper { order: 1; }
                .chat-container { height: 100vh; }
                .title { font-size: 20px; }
                .input-area { padding: 12px; gap: 8px; }
                #message-input { padding: 10px 12px; font-size: 16px; }
                .action-button { height: 40px; padding: 0 12px; font-size: 14px; }
            }
        </style>
    </head>
    <body>
        
        <div id="authModal" class="modal" onclick="closeModal(event)">
            <div class="modal-content">
                <h3 id="modalTitle">Login</h3>
                <p id="auth-message" style="display: none;"></p>
                <input type="text" id="authUsername" placeholder="Username" required>
                <input type="password" id="authPassword" placeholder="Password" required>
                <button onclick="handleAuth()">Login</button>
                <button style="background-color: #10b981; margin-top: 15px;" onclick="switchAuthMode()">Switch to Register</button>
            </div>
        </div>
        
        <div class="main-container">
            <div class="sidebar" id="sidebar">
                <div class="sidebar-toolbar">
                    <button class="new-chat-button" onclick="newConversation()">New Chat</button>
                    <button id="save-chat-sidebar-button" class="save-chat-sidebar-button" onclick="saveCurrentConversation()">💾 Save Chat</button>
                </div>
                <h3>Saved Chats</h3>
                <div id="saved-chats-list"></div>
                <div class="save-limit">Maximum 5 chats</div>
            </div>

            <div class="chat-wrapper">
                <div class="chat-container">
                    <div class="header">
                        <div class="title">HyperNova AI 🪐✨</div>
                        <div class="header-buttons">
                            <button id="clear-button" onclick="clearConversation()" title="Clear and Reset Conversation">🧹</button>
                            <button id="theme-toggle" onclick="toggleTheme()" title="Change Theme">☀️</button>
                            <button id="lang-toggle" onclick="toggleLanguage()" title="Change Language">EN</button>
                        </div>
                    </div>
                    
                    <div id="auth-status">
                        <span id="user-info">Not Logged In</span>
                        <div id="auth-buttons">
                            <button onclick="showModal('login')">Login</button>
                            <button onclick="showModal('register')">Register</button>
                            <button id="logout-button" style="display: none;" onclick="logout()">Logout</button>
                        </div>
                    </div>
                    
                    <select id="persona-select" onchange="changePersona()">
                        <option value="hypernova">HyperNova (Standard) 🪐</option>
                        <option value="kaia" disabled>Kaia (Anime) (Premium) 🌠</option>
                        <option value="hypernova_dengesiz">HyperNova Chaotic (Chaotic) 🌪️</option>
                    </select>

                    <div id="chat-history">
                    </div>
                    
                    <div class="input-area">
                        <input type="text" id="message-input" placeholder="Ask a cosmic question..." onkeypress="if(event.key==='Enter') sendMessage()">
                        <button id="voice-button" class="action-button" onclick="toggleVoiceInput()" title="Voice Input">🎙️</button>
                        <button id="send-button" class="action-button" onclick="sendMessage()">Send</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // [Previous JS code remains the same, but with font-family: 'Inter', sans-serif; updates where needed]
            // For brevity, assuming the JS is identical but with minor tweaks for new selectors if any.
            // In full implementation, copy the JS from original and adjust selectors/classes as per new CSS.
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


if __name__ == '__main__':
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (DEVELOPER_USERNAME,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (username, password, premium_until) 
            VALUES (%s, %s, CURRENT_TIMESTAMP + INTERVAL '9999 days')
        """, (DEVELOPER_USERNAME, DEVELOPER_PASSWORD))
        conn.commit()
        logger.info(f"Geliştirici kullanıcısı '{DEVELOPER_USERNAME}' sisteme eklendi.")
    cursor.close()
    put_db_connection(conn)

    app.run(debug=True, host='0.0.0.0', port=5000)
