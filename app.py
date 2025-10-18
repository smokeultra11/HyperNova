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
    "In Markdown, keep **bold text** and **emojies** (1-3, e.g. 🌟🍎🚀) minimal, only when necessary. "
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
    "In Markdown, use **bold text** and **emojies** (🌪️💥🔥) a lot. "
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

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL bulunamadı!")
    url = urlparse(DATABASE_URL)
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
    if not username:
        pass 

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
                is_authenticated = True
                return redirect(url_for('admin_panel', auth='success')) 
            else:
                return admin_login_template("Geçersiz Yönetici Kimlik Bilgisi."), 401

        elif form_type == 'premium_grant':
            admin_user = request.form.get('auth_username')
            admin_pass = request.form.get('auth_password')

            if not check_admin_auth(admin_user, admin_pass):
                return admin_login_template("Yetkisiz İşlem Denemesi. Lütfen Yönetici olarak giriş yapın."), 403

            is_authenticated = True

            target_username = request.form.get('target_username')

            if get_user_id(target_username) is None:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** bulunamadı."), 404

            if grant_premium(target_username):
                message = f"Başarılı! **{target_username}** kullanıcısının premium üyeliği **{ (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')}** tarihine kadar aktifleştirildi (30 gün)."
                return admin_panel_template(message, is_authenticated)
            else:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** premium verilemedi."), 500


    if request.args.get('auth') == 'success' or request.args.get('auth_user') == DEVELOPER_USERNAME:
        is_authenticated = True 

    if is_authenticated:
        return admin_panel_template("", is_authenticated)
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
    conn.close()

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
            
            <h2>Sistemdeki Tüm Kullanıcılar ({len(rows) if 'rows' in locals() else 0})</h2>
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
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #f0f2f5;
                --card-bg: #ffffff;
                --history-bg: #e5e5e5;
                --text-color: #1f2937;
                --user-bubble: #3b82f6;
                --bot-bubble: #f9fafb;
                --primary-color: #6366f1;
                --typing-color: #6366f1;
                --border-color: #d1d5db;
                --shadow-color: rgba(0,0,0,0.1);

                --kaia-primary-color: #ff69b4;
                --kaia-bot-bubble: #ffe4e6;
                --kaia-text-color: #e91e63;
            }

            @media (prefers-color-scheme: dark) {
                :root {
                    --bg-color: #0d1117;
                    --card-bg: #161b22;
                    --history-bg: #21262d;
                    --text-color: #e6edf3;
                    --user-bubble: #4c51bf;
                    --bot-bubble: #2d3748;
                    --primary-color: #8b5cf6;
                    --typing-color: #a78bfa;
                    --border-color: #30363d;
                    --shadow-color: rgba(0,0,0,0.7);

                    --kaia-primary-color: #ffb6c1;
                    --kaia-bot-bubble: #4a2333;
                    --kaia-text-color: #ffb6c1;
                }
            }
            
            body.light-theme {
                --bg-color: #f0f2f5; --card-bg: #ffffff; --history-bg: #e5e5e5; --text-color: #1f2937;
                --user-bubble: #3b82f6; --bot-bubble: #f9fafb; --primary-color: #6366f1; --typing-color: #6366f1;
                --border-color: #d1d5db; --shadow-color: rgba(0,0,0,0.1);
            }
            body.dark-theme {
                --bg-color: #0d1117; --card-bg: #161b22; --history-bg: #21262d; --text-color: #e6edf3;
                --user-bubble: #4c51bf; --bot-bubble: #2d3748; --primary-color: #8b5cf6; --typing-color: #a78bfa;
                --border-color: #30363d; --shadow-color: rgba(0,0,0,0.7);
            }

            body.kaia-theme {
                background-color: var(--kaia-bot-bubble);
                --card-bg: var(--kaia-bot-bubble);
                --history-bg: #fff0f5;
                --user-bubble: #ff69b4;
                --bot-bubble: #ffffff;
                --primary-color: var(--kaia-primary-color);
                --text-color: #1f2937;

                @media (prefers-color-scheme: dark) {
                    --bg-color: #2a0c1a;
                    --card-bg: #2a0c1a;
                    --history-bg: #3c1626;
                    --user-bubble: #ffb6c1;
                    --bot-bubble: #5c3044;
                    --text-color: #fff0f5;
                }
            }
            
            body {  
                background-color: var(--bg-color);  
                color: var(--text-color);  
                font-family: 'Montserrat', sans-serif;
                margin: 0;  
                padding: 0;  
                min-height: 100vh;  
                transition: background-color 0.4s ease;
            }

            .main-container {
                display: flex;
                height: 100vh;
                max-width: 100vw;
                overflow: hidden;
            }

            .sidebar {
                width: 280px;
                background: linear-gradient(180deg, var(--card-bg) 0%, rgba(255,255,255,0.8) 100%);
                border-right: 1px solid var(--border-color);
                padding: 20px 0;
                overflow-y: auto;
                box-shadow: 4px 0 20px var(--shadow-color);
                display: flex;
                flex-direction: column;
                transition: width 0.3s ease;
            }
            .sidebar:hover {
                box-shadow: 4px 0 30px var(--shadow-color);
            }
            .sidebar h3 {
                padding: 0 20px 15px;
                margin: 0;
                color: var(--primary-color);
                font-size: 16px;
                font-weight: 600;
                border-bottom: 1px solid var(--border-color);
                letter-spacing: 0.5px;
            }
            .sidebar-toolbar {
                padding: 0 16px 16px;
                display: flex;
                flex-direction: column;
                gap: 8px;
                border-bottom: 1px solid var(--border-color);
            }
            .new-chat-button, .save-chat-sidebar-button {
                padding: 12px;
                background: linear-gradient(135deg, var(--primary-color), #a78bfa);
                color: white;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Montserrat', sans-serif;
                transition: all 0.3s ease;
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .new-chat-button:hover, .save-chat-sidebar-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
            }
            .save-chat-sidebar-button {
                background: linear-gradient(135deg, #10b981, #059669);
                box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            }
            .save-chat-sidebar-button:hover {
                box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
            }
            .saved-chat {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                cursor: pointer;
                border-bottom: 1px solid rgba(209, 213, 219, 0.2);
                transition: all 0.3s ease;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Montserrat', sans-serif;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                position: relative;
                animation: slideInLeft 0.4s ease-out forwards;
            }
            .saved-chat:nth-child(even) {
                background: rgba(209, 213, 219, 0.1);
            }
            .saved-chat:hover {
                background: linear-gradient(90deg, var(--primary-color), #a78bfa);
                color: white;
                transform: translateX(5px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
            }
            .saved-chat.active {
                background: linear-gradient(135deg, var(--primary-color), #a78bfa);
                color: white;
                box-shadow: inset 0 0 0 2px rgba(255,255,255,0.2);
            }
            .saved-chat-name {
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                font-weight: 500;
            }
            .delete-chat-button {
                background: none;
                border: none;
                color: inherit;
                cursor: pointer;
                font-size: 16px;
                padding: 4px 8px;
                border-radius: 50%;
                transition: all 0.2s ease;
                opacity: 0.7;
            }
            .saved-chat:hover .delete-chat-button {
                opacity: 1;
                background: rgba(255,255,255,0.2);
            }
            .delete-chat-button:hover {
                background: rgba(239, 68, 68, 0.3);
                color: #ef4444;
            }
            .save-limit {
                padding: 12px 20px;
                text-align: center;
                font-size: 12px;
                color: var(--text-color);
                opacity: 0.6;
                font-style: italic;
                font-family: 'Montserrat', sans-serif;
            }

            @keyframes slideInLeft {
                from {
                    opacity: 0;
                    transform: translateX(-20px);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }

            .chat-wrapper {
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 10px;
            }
            .chat-container {  
                width: 100%;
                max-width: 600px;
                height: 90vh;
                max-height: 800px;
                background-color: var(--card-bg);  
                border-radius: 16px;
                padding: 20px;
                box-shadow: 0 10px 40px var(--shadow-color);  
                display: flex;  
                flex-direction: column;  
                border: 1px solid var(--border-color);
                transition: all 0.4s ease;
                margin: 0;
            }
            
            #auth-status {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-top: 5px;
                margin-bottom: 10px;
                padding: 5px 10px;
                background-color: var(--history-bg);
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                color: var(--text-color);
                justify-content: space-between;
                font-family: 'Montserrat', sans-serif;
            }
            #auth-status button, #logout-button {
                background: var(--primary-color);
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 600;
                transition: background 0.2s;
                font-family: 'Montserrat', sans-serif;
            }
            #auth-status button:hover, #logout-button:hover {
                background: #a78bfa;
            }
            .premium-tag {
                background-color: #facc15;
                color: #854d0e;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 700;
                margin-left: 5px;
                line-height: 1;
            }

            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 5px;
            }
            .title {  
                font-size: 26px;  
                font-weight: 700;
                color: var(--primary-color);
                letter-spacing: -0.5px;
                text-shadow: 0 0 5px rgba(139, 92, 246, 0.4);
                transition: color 0.4s ease, text-shadow 0.4s ease;
                font-family: 'Montserrat', sans-serif;
            }
            #theme-toggle, #clear-button, #lang-toggle {
                background: var(--history-bg);
                color: var(--text-color);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 8px 12px;
                cursor: pointer;
                transition: background 0.2s, transform 0.1s;
                font-size: 18px;
                margin-left: 5px;
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
                border-radius: 8px;
                border: 1px solid var(--border-color);
                background-color: var(--card-bg);
                color: var(--text-color);
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
                margin-top: 10px;
                margin-bottom: 20px;
                transition: all 0.3s;
                appearance: none;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%236B7280' d='M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 12px center;
                padding-right: 30px;
                font-family: 'Montserrat', sans-serif;
            }
            #persona-select:disabled {
                cursor: not-allowed;
                opacity: 0.7;
                border-style: dashed;
            }
            body.kaia-theme #persona-select {
                border-color: var(--kaia-primary-color);
                color: var(--kaia-text-color);
                background-color: #ffffff;
            }

            #chat-history {  
                flex: 1;  
                background-color: var(--history-bg);  
                border-radius: 12px;  
                padding: 15px;  
                overflow-y: auto;  
                font-size: 15px;  
                line-height: 1.6;  
                margin-bottom: 15px;  
                scroll-behavior: smooth;
                box-shadow: inset 0 2px 5px rgba(0,0,0,0.05);
                font-family: 'Montserrat', sans-serif;
            }
            #chat-history::-webkit-scrollbar {
                width: 8px;
            }
            #chat-history::-webkit-scrollbar-thumb {
                background-color: var(--border-color);
                border-radius: 4px;
            }

            .message {  
                margin-bottom: 15px;  
                padding: 12px 18px;  
                border-radius: 20px;
                max-width: 85%;
                word-wrap: break-word;
                animation: fadeIn 0.3s ease-out;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                font-family: 'Montserrat', sans-serif;
            }
            .user {  
                background-color: var(--user-bubble);  
                color: white;  
                margin-left: auto;
                border-bottom-right-radius: 4px;
            }
            .bot {  
                background-color: var(--bot-bubble);  
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
                font-weight: 700;
                color: var(--primary-color);
                transition: color 0.4s;
            }
            .user strong {
                color: #fff;
            }
            .bot strong {
                color: var(--typing-color);
            }


            .input-area {  
                display: flex;  
                gap: 10px;
                align-items: center;
            }
            #message-input {  
                flex: 1;  
                padding: 14px;  
                border: 1px solid var(--border-color);
                border-radius: 10px;
                background-color: var(--card-bg);
                color: var(--text-color);
                font-size: 16px;
                resize: none;
                transition: border-color 0.3s, box-shadow 0.3s;
                font-family: 'Montserrat', sans-serif;
            }
            #message-input:focus {
                border-color: var(--primary-color);
                box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.3);
                outline: none;
            }
            .action-button {  
                padding: 0 16px;
                background-color: var(--primary-color);  
                color: white;  
                border: none;  
                border-radius: 10px;
                cursor: pointer;  
                font-weight: 600;
                transition: background-color 0.2s, transform 0.1s, box-shadow 0.2s;
                display: flex;
                align-items: center;
                height: 48px;
                font-size: 16px;
                font-family: 'Montserrat', sans-serif;
            }
            .action-button:hover {  
                background-color: #a78bfa;
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(139, 92, 246, 0.4);
            }
            .action-button:disabled {
                background-color: var(--border-color);
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }
            #voice-button.listening {
                background-color: #ef4444;
            }

            .modal {
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                overflow: auto;
                background-color: rgba(0,0,0,0.4);
                display: none;
                justify-content: center;
                align-items: center;
            }
            .modal-content {
                background-color: var(--card-bg);
                padding: 30px;
                border-radius: 10px;
                width: 90%;
                max-width: 400px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.5);
                text-align: center;
                font-family: 'Montserrat', sans-serif;
            }
            .modal-content h3 {
                color: var(--primary-color);
                margin-top: 0;
                margin-bottom: 20px;
            }
            .modal-content input {
                width: 100%;
                padding: 10px;
                margin-bottom: 15px;
                border: 1px solid var(--border-color);
                border-radius: 6px;
                box-sizing: border-box;
                background-color: var(--history-bg);
                color: var(--text-color);
                font-family: 'Montserrat', sans-serif;
            }
            .modal-content button {
                width: 100%;
                padding: 10px;
                margin-top: 5px;
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-weight: bold;
                font-family: 'Montserrat', sans-serif;
            }
            .modal-content button:hover {
                background-color: #a78bfa;
            }
            #auth-message {
                color: #ef4444;
                margin-bottom: 15px;
            }

            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                color: var(--typing-color);
                font-style: italic;
                padding: 12px 18px;
                margin-right: auto;
                border-radius: 20px;
                font-family: 'Montserrat', sans-serif;
            }
            .spinner {
                width: 10px;
                height: 10px;
                background-color: var(--typing-color);
                border-radius: 50%;
                opacity: 0;
                animation: dot-pulse 1.5s infinite;
            }
            .spinner:nth-child(2) {
                animation-delay: 0.2s;
            }
            .spinner:nth-child(3) {
                animation-delay: 0.4s;
            }

            @keyframes dot-pulse {
                0%, 100% { transform: scale(0.8); opacity: 0.5; }
                50% { transform: scale(1.2); opacity: 1; }
            }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            @media (max-width: 900px) {
                .main-container {
                    flex-direction: column;
                }
                .sidebar {
                    width: 100%;
                    height: auto;
                    order: 2;
                }
                .chat-wrapper {
                    order: 1;
                }
                .chat-container {
                    height: 70vh;
                }
            }
            @media (max-width: 640px) {
                .chat-container {
                    width: 100%;
                    height: 70vh;
                    padding: 15px;
                    border-radius: 0;
                    box-shadow: none;
                    margin: 0;
                }
                .title {
                    font-size: 22px;
                }
                .input-area {
                    flex-direction: row;
                    gap: 5px;
                }
                .action-button {
                    height: 44px;
                    padding: 0 10px;
                    font-size: 15px;
                }
                #message-input {
                    padding: 10px;
                    font-size: 15px;
                }
                .header-buttons button {
                    font-size: 16px;
                    padding: 6px 10px;
                }
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
            let conversation = [];
            let isThinking = false;
            let isVoiceListening = false;
            let savedConversations = [];
            let currentLoadedChatId = null;
            let isCurrentSaved = false;
            
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');
            const voiceButton = document.getElementById('voice-button');
            const themeToggle = document.getElementById('theme-toggle');
            const clearButton = document.getElementById('clear-button');
            const personaSelect = document.getElementById('persona-select');
            const kaiaOption = personaSelect.querySelector('option[value="kaia"]');
            const sidebar = document.getElementById('sidebar');
            const savedChatsList = document.getElementById('saved-chats-list');

            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let authMode = 'login';
            let currentLang = localStorage.getItem('lang') || 'en';

            const TRANSLATIONS = {
                en: {
                    newChat: 'New Chat',
                    saveChat: '💾 Save Chat',
                    savedChats: 'Saved Chats',
                    maxChats: 'Maximum 5 chats',
                    clearTitle: 'Clear and Reset Conversation',
                    themeTitle: 'Change Theme',
                    voiceTitle: 'Voice Input',
                    langTitle: 'Change Language',
                    send: 'Send',
                    login: 'Login',
                    register: 'Register',
                    logout: 'Logout',
                    welcome: 'Welcome, ',
                    notLoggedIn: 'Not Logged In',
                    modalLogin: 'Login',
                    modalRegister: 'Register',
                    switchRegister: 'Switch to Register',
                    switchLogin: 'Switch to Login',
                    usernamePH: 'Username',
                    passwordPH: 'Password',
                    emptyCred: 'Username and password cannot be empty.',
                    networkError: 'Network Error. Please try again.',
                    authReqSave: 'You must log in to save conversation.',
                    authReqLoad: 'You must log in to load conversation.',
                    authReqDelete: 'You must log in to delete conversation.',
                    chatsLoadError: 'Chats could not be loaded: ',
                    saveError: 'Save error: ',
                    loadError: 'Load error: ',
                    deleteError: 'Delete error: ',
                    thinkingNew: 'Wait for new chat, system is busy. ⏳',
                    thinkingClear: 'Wait for reset, system is busy. ⏳',
                    voiceDisabled: 'Voice input is not active in this demo. 🎤',
                    errorPrefix: '**ERROR:** ',
                    aiConnectFailed: 'AI connection could not be established. Please try again in a short while. ',
                    unknownError: 'Unknown Error',
                    serverError: '**ERROR:** Could not reach server. Check your internet connection. ⚠️',
                    kaiaForce: 'Kaia mode requires Premium, switching to HyperNova.',
                    newConvSaveConfirm: 'Starting new chat. Save current conversation? (Cancel to keep current)',
                    discardConfirm: 'Are you sure you want to continue without saving?',
                    newConvStarted: 'New conversation started! ✨',
                    clearConfirm: 'Conversation history will be cleared. Are you sure? 🤔',
                    cleared: 'Conversation history cleared. Starting over. ✅',
                    savePrompt: 'Enter chat name:',
                    saveNoName: 'Chat name required.',
                    saveMinMsg: 'No conversation to save. Send at least one message.',
                    saveMax: 'Maximum 5 chats can be saved. Delete an old one.',
                    saved: 'Conversation "',
                    savedMsg: '" saved. 💾',
                    loaded: ' conversation loaded.',
                    deleteConfirm: 'This conversation will be deleted. Are you sure?',
                    deleted: 'Conversation deleted. 🗑️',
                    changeConfirm: 'You are about to change to %s mode. ',
                    historyWillClear: 'The history will be cleared.',
                    sure: 'Are you sure?',
                    modeChangedTo: 'Mode changed to ',
                    newChatStarted: '. New conversation started!',
                    kaiaPremiumReq: "Kaia (Anime Girl) mode is reserved for **Premium** subscribers. Please log in or become a premium subscriber. 🚫",
                    welcomePremium: 'Your premium membership is active. ✨',
                    welcomeFree: 'You can chat with HyperNova for free.',
                    desc_hypernova: 'HyperNova (Standard)',
                    desc_kaia: 'Kaia (Anime Girl)',
                    desc_hypernova_dengesiz: 'HyperNova Chaotic (Chaotic)',
                    name_hypernova: 'HyperNova',
                    name_kaia: 'Kaia',
                    name_hypernova_dengesiz: 'HyperNova Chaotic',
                    persona: {
                        hypernova: 'HyperNova (Standard) 🪐',
                        kaia: 'Kaia (Anime) (Premium) 🌠',
                        hypernova_dengesiz: 'HyperNova Chaotic (Chaotic) 🌪️'
                    }
                },
                tr: {
                    newChat: 'Yeni Sohbet',
                    saveChat: '💾 Sohbeti Kaydet',
                    savedChats: 'Kaydedilen Sohbetler',
                    maxChats: 'Maksimum 5 sohbet',
                    clearTitle: 'Sohbeti Temizle ve Sıfırla',
                    themeTitle: 'Temayı Değiştir',
                    voiceTitle: 'Sesli Giriş',
                    langTitle: 'Dil Değiştir',
                    send: 'Gönder',
                    login: 'Giriş Yap',
                    register: 'Kayıt Ol',
                    logout: 'Çıkış Yap',
                    welcome: 'Hoş geldin, ',
                    notLoggedIn: 'Giriş Yapılmadı',
                    modalLogin: 'Oturum Aç',
                    modalRegister: 'Kayıt Ol',
                    switchRegister: "Kayıt Ol'a Geç",
                    switchLogin: "Giriş Yap'a Geç",
                    usernamePH: 'Kullanıcı Adı',
                    passwordPH: 'Şifre',
                    emptyCred: 'Kullanıcı adı ve şifre boş olamaz.',
                    networkError: 'Ağ Hatası. Lütfen tekrar deneyin.',
                    authReqSave: 'Sohbet kaydetmek için giriş yapmalısınız.',
                    authReqLoad: 'Sohbet yüklemek için giriş yapmalısınız.',
                    authReqDelete: 'Sohbet silmek için giriş yapmalısınız.',
                    chatsLoadError: 'Sohbetler yüklenemedi: ',
                    saveError: 'Kaydetme hatası: ',
                    loadError: 'Yükleme hatası: ',
                    deleteError: 'Silme hatası: ',
                    thinkingNew: 'Yeni sohbet için bekle, sistem meşgul. ⏳',
                    thinkingClear: 'Sıfırlama işlemi için bekle, sistem meşgul. ⏳',
                    voiceDisabled: 'Sesli giriş özelliği bu demoda aktif değil. 🎤',
                    errorPrefix: '**HATA:** ',
                    aiConnectFailed: 'Yapay zeka ile bağlantı kurulamadı. Lütfen kısa bir süre sonra tekrar deneyin. ',
                    unknownError: 'Bilinmeyen Hata',
                    serverError: '**HATA:** Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edin. ⚠️',
                    kaiaForce: "Kaia modu Premium gerektirdiği için HyperNova'ya geçildi.",
                    newConvSaveConfirm: 'Yeni sohbet başlatılacak. Mevcut sohbet kaydedilsin mi? (Vazgeçersen mevcut kalır)',
                    discardConfirm: 'Kaydetmeden devam etmek istediğinize emin misiniz?',
                    newConvStarted: 'Yeni sohbet başlatıldı! ✨',
                    clearConfirm: 'Konuşma geçmişi silinecek. Emin misin? 🤔',
                    cleared: 'Sohbet geçmişi silindi. Sıfırdan başlıyoruz. ✅',
                    savePrompt: 'Sohbet adı girin:',
                    saveNoName: 'Sohbet adı zorunlu.',
                    saveMinMsg: 'Kaydedilecek sohbet yok. En az bir mesaj gönderin.',
                    saveMax: 'Maksimum 5 sohbet kaydedilebilir. Eski bir sohbeti silin.',
                    saved: 'Sohbet "',
                    savedMsg: '" kaydedildi. 💾',
                    loaded: ' sohbeti yüklendi.',
                    deleteConfirm: 'Bu sohbet silinecek. Emin misin?',
                    deleted: 'Sohbet silindi. 🗑️',
                    changeConfirm: '%s olarak değiştirmek üzeresin. ',
                    historyWillClear: 'Geçmiş silinecek.',
                    sure: 'Emin misin?',
                    modeChangedTo: 'Mod ',
                    newChatStarted: ' olarak değiştirildi. Yeni sohbet başlatıldı!',
                    kaiaPremiumReq: "Kaia (Anime Kızı) modu **Premium** aboneler için ayrılmıştır. Lütfen giriş yapın veya premium abonesi olun. 🚫",
                    welcomePremium: 'Premium üyeliğin aktif. ✨',
                    welcomeFree: 'HyperNova ile ücretsiz sohbet edebilirsin.',
                    desc_hypernova: 'HyperNova (Standart)',
                    desc_kaia: 'Kaia (Anime Kızı)',
                    desc_hypernova_dengesiz: 'HyperNova Dengesiz (Kaotik)',
                    name_hypernova: 'HyperNova',
                    name_kaia: 'Kaia',
                    name_hypernova_dengesiz: 'HyperNova Dengesiz',
                    persona: {
                        hypernova: 'HyperNova (Standart) 🪐',
                        kaia: 'Kaia (Anime) (Premium) 🌠',
                        hypernova_dengesiz: 'HyperNova Dengesiz (Kaotik) 🌪️'
                    }
                }
            };

            const GREETINGS = {
                en: {
                    hypernova: {
                        text: "**HyperNova** is here. I am an artificial intelligence with access to the universal database. 🌌 Clearly state what you want to learn. I focus on conveying accurate and correct information. ✨",
                        title: "HyperNova AI 🪐✨",
                        placeholder: "Ask a cosmic question..."
                    },
                    kaia: {
                        text: "**Kaia** with you! 💖 How are you today? You can ask me anything, I'll answer in the sweetest way! Shall we start right away? 🌸",
                        title: "Kaia AI 💖🌸",
                        placeholder: "Say something sweet to Kaia..."
                    },
                    hypernova_dengesiz: {
                        text: "**HyperNova Chaotic** here, the lord of chaos! 🌪️ Tell me whatever shitty thing you want, I'll answer without judging (maybe a little). Are you ready, idiot? 💥",
                        title: "HyperNova Chaotic 🌪️💥",
                        placeholder: "Ask a chaotic question..."
                    }
                },
                tr: {
                    hypernova: {
                        text: "**HyperNova** burada. Evrensel veri tabanına erişimi olan yapay zekayım. 🌌 Ne öğrenmek istediğini açıkça belirt. Kesin ve doğru bilgi aktarmaya odaklıyım. ✨",
                        title: "HyperNova AI 🪐✨",
                        placeholder: "Kozmik bir soru sor..."
                    },
                    kaia: {
                        text: "**Kaia** seninle! 💖 Bugün nasılsın? Bana her şeyi sorabilirsin, sana en tatlı şekilde cevap vereceğim! Hemen başlayalım mı? 🌸",
                        title: "Kaia AI 💖🌸",
                        placeholder: "Kaia'ya tatlı bir şey söyle..."
                    },
                    hypernova_dengesiz: {
                        text: "**HyperNova Dengesiz** burada, kaosun efendisi! 🌪️ Ne boktan bir şey istersen söyle, seni yargılamadan (belki biraz) cevap veririm. Hazır mısın aptal? 💥",
                        title: "HyperNova Dengesiz 🌪️💥",
                        placeholder: "Dengesiz bir soru sor..."
                    }
                }
            };

            let currentPersona = localStorage.getItem('current_persona') || 'hypernova';
            let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

            function parseMarkdown(text) {
                text = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                text = text.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
                text = text.replace(/\\[(.*?)\\]\\((.*?)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                return text;
            }

            function getPersonaDesc(persona) {
                return TRANSLATIONS[currentLang][`desc_${persona}`];
            }

            function getPersonaName(persona) {
                return TRANSLATIONS[currentLang][`name_${persona}`];
            }

            function toggleLanguage() {
                currentLang = currentLang === 'en' ? 'tr' : 'en';
                localStorage.setItem('lang', currentLang);
                document.cookie = `lang=${currentLang}; max-age=${7*24*60*60}; path=/`;
                updateLanguage();
                updateUIForPersona();
            }

            function updateLanguage() {
                const t = TRANSLATIONS[currentLang];
                document.querySelector('.new-chat-button').textContent = t.newChat;
                document.getElementById('save-chat-sidebar-button').textContent = t.saveChat;
                document.querySelector('.sidebar h3').textContent = t.savedChats;
                document.querySelector('.save-limit').textContent = t.maxChats;
                document.getElementById('send-button').textContent = t.send;
                document.getElementById('clear-button').title = t.clearTitle;
                document.getElementById('theme-toggle').title = t.themeTitle;
                document.getElementById('voice-button').title = t.voiceTitle;
                document.getElementById('lang-toggle').title = t.langTitle;
                document.getElementById('lang-toggle').textContent = currentLang.toUpperCase();
                const kaiaDisabled = isPremium ? '' : 'disabled';
                const selectedHyper = currentPersona === 'hypernova' ? 'selected' : '';
                const selectedDeng = currentPersona === 'hypernova_dengesiz' ? 'selected' : '';
                personaSelect.innerHTML = `
                    <option value="hypernova" ${selectedHyper}>${t.persona.hypernova}</option>
                    <option value="kaia" ${kaiaDisabled}>${t.persona.kaia}</option>
                    <option value="hypernova_dengesiz" ${selectedDeng}>${t.persona.hypernova_dengesiz}</option>
                `;
                personaSelect.value = currentPersona;
                document.title = currentLang === 'en' ? 'HyperNova AI ✦ Cosmic Intelligence' : 'HyperNova AI ✦ Kozmik Zeka';
                document.documentElement.lang = currentLang;
            }

            async function saveCurrentConversation() {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqSave);
                    return;
                }
                if (conversation.length < 2) {
                    alertMessage(t.saveMinMsg);
                    return;
                }

                const chatName = prompt(t.savePrompt);
                if (!chatName || chatName.trim() === '') {
                    alertMessage(t.saveNoName);
                    return;
                }

                const userChats = await loadUserChats();
                if (userChats.chats.length >= 5) {
                    alertMessage(t.saveMax);
                    return;
                }

                try {
                    const response = await fetch('/save_chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: chatName.trim(), messages: conversation })
                    });

                    const data = await response.json();
                    if (response.ok) {
                        isCurrentSaved = true;
                        currentLoadedChatId = data.chat_id;
                        await loadUserChats();
                        alertMessage(`${t.saved}"${chatName.trim()}"${t.savedMsg}`);
                    } else {
                        alertMessage(`${t.saveError}${data.error}`);
                    }
                } catch (error) {
                    alertMessage(t.networkError);
                }
            }

            async function loadUserChats() {
                const t = TRANSLATIONS[currentLang];
                try {
                    const response = await fetch('/load_chats');
                    const data = await response.json();
                    if (response.ok) {
                        savedConversations = data.chats;
                        updateSavedChatsList();
                        return data;
                    } else {
                        alertMessage(`${t.chatsLoadError}${data.error}`);
                    }
                } catch (error) {
                }
                savedConversations = [];
                updateSavedChatsList();
                return { chats: [] };
            }

            async function loadSavedConversation(chatId) {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqLoad);
                    return;
                }
                try {
                    const response = await fetch(`/load_chat/${chatId}`);
                    const data = await response.json();
                    if (response.ok) {
                        const chat = data.chat;
                        conversation = chat.messages;
                        historyDiv.innerHTML = '';
                        conversation.forEach(msg => {
                            if (msg.role !== 'system') {
                                displayMessage(msg.role, msg.content, false);
                            }
                        });
                        scrollToBottom();

                        currentLoadedChatId = chatId;
                        isCurrentSaved = true;
                        updateSavedChatsList();

                        alertMessage(`"${chat.name}"${t.loaded}`);
                    } else {
                        alertMessage(`${t.loadError}${data.error}`);
                        if (data.error.includes('not found') || data.error.includes('bulunamadı')) {
                            await deleteSavedConversation(chatId);
                        }
                    }
                } catch (error) {
                    alertMessage(t.networkError);
                }
            }

            async function deleteSavedConversation(chatId, event) {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqDelete);
                    return;
                }
                event.stopPropagation();
                if (confirm(t.deleteConfirm)) {
                    try {
                        const response = await fetch(`/delete_chat/${chatId}`, { method: 'DELETE' });
                        const data = await response.json();
                        if (response.ok) {
                            if (currentLoadedChatId === chatId) {
                                currentLoadedChatId = null;
                                isCurrentSaved = false;
                                newConversation();
                            }
                            await loadUserChats();
                            alertMessage(t.deleted);
                        } else {
                            alertMessage(`${t.deleteError}${data.error}`);
                        }
                    } catch (error) {
                        alertMessage(t.networkError);
                    }
                }
            }

            function updateSavedChatsList() {
                savedChatsList.innerHTML = '';
                savedConversations.forEach((chat, index) => {
                    const chatElement = document.createElement('div');
                    chatElement.className = 'saved-chat';
                    chatElement.style.animationDelay = `${index * 0.1}s`;
                    if (currentLoadedChatId === chat.id) {
                        chatElement.classList.add('active');
                    }
                    chatElement.innerHTML = `
                        <span class="saved-chat-name" onclick="loadSavedConversation('${chat.id}')">${chat.name}</span>
                        <button class="delete-chat-button" onclick="deleteSavedConversation('${chat.id}', event)" title="Delete Conversation">🗑️</button>
                    `;
                    savedChatsList.appendChild(chatElement);
                });
            }

            function newConversation() {
                const t = TRANSLATIONS[currentLang];
                if (isThinking) {
                    alertMessage(t.thinkingNew);
                    return;
                }
                let needsSave = !isCurrentSaved && conversation.length >= 2;
                if (needsSave && confirm(t.newConvSaveConfirm)) {
                    saveCurrentConversation();
                } else if (needsSave && !confirm(t.discardConfirm)) {
                    return;
                }
                clearConversation(true);
                currentLoadedChatId = null;
                isCurrentSaved = false;
                updateSavedChatsList();
                alertMessage(t.newConvStarted);
            }

            function showModal(mode) {
                const t = TRANSLATIONS[currentLang];
                authMode = mode;
                document.getElementById('modalTitle').textContent = mode === 'login' ? t.modalLogin : t.modalRegister;
                document.querySelector('.modal-content button:first-of-type').textContent = mode === 'login' ? t.login : t.register;
                document.querySelector('.modal-content button:last-of-type').textContent = mode === 'login' ? t.switchRegister : t.switchLogin;
                document.getElementById('authUsername').placeholder = t.usernamePH;
                document.getElementById('authPassword').placeholder = t.passwordPH;
                document.getElementById('auth-message').style.display = 'none';
                document.getElementById('authModal').style.display = 'flex';
                document.getElementById('authUsername').focus();
            }

            function closeModal(event) {
                const modal = document.getElementById('authModal');
                if (event && event.target === modal) {
                    modal.style.display = 'none';
                }
            }

            function switchAuthMode() {
                authMode = authMode === 'login' ? 'register' : 'login';
                showModal(authMode);
            }
            
            async function handleAuth() {
                const t = TRANSLATIONS[currentLang];
                const username = document.getElementById('authUsername').value.trim();
                const password = document.getElementById('authPassword').value;
                const messageElement = document.getElementById('auth-message');
                
                messageElement.style.display = 'none';
                
                if (!username || !password) {
                    messageElement.textContent = t.emptyCred;
                    messageElement.style.display = 'block';
                    return;
                }
                
                const endpoint = authMode === 'login' ? '/login' : '/register';
                
                try {
                    const response = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        messageElement.textContent = data.message;
                        messageElement.style.color = '#10b981';
                        messageElement.style.display = 'block';
                        
                        if (authMode === 'login') {
                            await checkAuthStatus();
                            document.getElementById('authModal').style.display = 'none';
                            await loadUserChats();
                            const welcomeMsg = `${t.welcome}${currentUsername}! ${isPremium ? t.welcomePremium : t.welcomeFree}`;
                            alertMessage(welcomeMsg);
                        } else {
                             switchAuthMode();
                        }
                    } else {
                        messageElement.textContent = `Error: ${data.error}`;
                        messageElement.style.color = '#ef4444';
                        messageElement.style.display = 'block';
                    }
                    
                } catch (error) {
                    messageElement.textContent = t.networkError;
                    messageElement.style.color = '#ef4444';
                    messageElement.style.display = 'block';
                }
            }
            
            async function logout() {
                try {
                    const response = await fetch('/logout', { method: 'POST' });
                    if (response.ok) {
                        await checkAuthStatus();
                        savedConversations = [];
                        updateSavedChatsList();
                        alertMessage(TRANSLATIONS[currentLang].logout);
                        if (currentPersona === 'kaia') {
                             currentPersona = 'hypernova';
                             localStorage.setItem('current_persona', 'hypernova');
                             clearConversation(true);
                        }
                        updateUIForPersona();
                    }
                } catch (error) {
                }
            }
            
            async function checkAuthStatus() {
                try {
                    const response = await fetch('/is_premium');
                    const data = await response.json();
                    
                    isLoggedIn = data.logged_in;
                    currentUsername = data.username;
                    isPremium = data.is_premium;
                    
                    const t = TRANSLATIONS[currentLang];
                    const authStatusDiv = document.getElementById('auth-status');
                    const userInfoSpan = document.getElementById('user-info');
                    const authButtonsDiv = document.getElementById('auth-buttons');
                    
                    if (isLoggedIn) {
                        authButtonsDiv.innerHTML = `<button id="logout-button" onclick="logout()">${t.logout}</button>`;
                        
                        let premiumInfo = '';
                        if (isPremium) {
                            premiumInfo = `<span class="premium-tag" title="Bitiş: ${data.premium_until}">⭐ PREMIUM</span>`;
                        }
                        
                        userInfoSpan.innerHTML = `${t.welcome}<strong>${currentUsername}</strong>${premiumInfo}`;

                    } else {
                        userInfoSpan.innerHTML = t.notLoggedIn;
                        authButtonsDiv.innerHTML = `
                            <button onclick="showModal('login')">${t.login}</button>
                            <button onclick="showModal('register')">${t.register}</button>
                        `;
                        isPremium = false;
                        savedConversations = [];
                        updateSavedChatsList();
                    }
                    
                } catch (error) {
                }
            }
            

            function applyTheme(theme) {
                document.body.classList.remove('light-theme', 'dark-theme', 'kaia-theme');
                if (currentPersona === 'kaia') {
                    document.body.classList.add('kaia-theme');
                } else {
                    document.body.classList.add(theme + '-theme');
                }
                themeToggle.textContent = theme === 'dark' ? '🌙' : '☀️';
                localStorage.setItem('theme', theme);
            }

            function toggleTheme() {
                currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                applyTheme(currentTheme);
            }
            
            function updateUIForPersona() {
                const t = TRANSLATIONS[currentLang];
                const persona = currentPersona;
                const greeting = GREETINGS[currentLang][persona];
                const titleElement = document.querySelector('.title');

                titleElement.textContent = greeting.title;
                input.placeholder = greeting.placeholder;
                
                applyTheme(currentTheme);

                personaSelect.value = persona;
                
                if (persona === 'kaia' && !isPremium) {
                    alertMessage(t.kaiaPremiumReq);
                    currentPersona = 'hypernova';
                    localStorage.setItem('current_persona', 'hypernova');
                    updateUIForPersona();
                    return;
                }
            }

            function changePersona() {
                const t = TRANSLATIONS[currentLang];
                const newPersona = personaSelect.value;
                
                if (newPersona === 'kaia' && !isPremium) {
                    alertMessage(t.kaiaPremiumReq);
                    personaSelect.value = currentPersona; 
                    return;
                }
                
                if (newPersona !== currentPersona) {
                    const desc = getPersonaDesc(newPersona);
                    const confirmMsg = t.changeConfirm.replace('%s', desc) + t.historyWillClear + '. ' + t.sure + '?';
                    if (confirm(confirmMsg)) {
                        currentPersona = newPersona;
                        localStorage.setItem('current_persona', newPersona);
                        clearConversation(true);
                        updateUIForPersona();
                        const name = getPersonaName(newPersona);
                        alertMessage(t.modeChangedTo + name + t.newChatStarted);
                    } else {
                        personaSelect.value = currentPersona;
                    }
                }
            }


            function clearConversation(isSilent = false) {
                const t = TRANSLATIONS[currentLang];
                if (isThinking) {
                    if (!isSilent) alertMessage(t.thinkingClear);
                    return;
                }
                
                if (isSilent || confirm(t.clearConfirm)) {
                    conversation = [];
                    historyDiv.innerHTML = '';
                    displayInitialGreeting();
                    currentLoadedChatId = null;
                    isCurrentSaved = false;
                    updateSavedChatsList();
                    if (!isSilent) alertMessage(t.cleared);
                }
            }

            function displayInitialGreeting() {
                const greetingText = GREETINGS[currentLang][currentPersona].text;
                displayMessage('bot', greetingText, false);
                conversation = [{role: 'bot', content: greetingText}];
                isCurrentSaved = false;
            }

            async function sendMessage() {
                const t = TRANSLATIONS[currentLang];
                const text = input.value.trim();
                if (text === '' || isThinking) return;

                input.value = '';
                displayMessage('user', text);
                
                isThinking = true;
                setControlsDisabled(true);
                const typingIndicator = displayTypingIndicator();

                try {
                    conversation.push({ role: 'user', content: text });

                    const apiMessages = conversation.map(msg => ({ role: msg.role, content: msg.content }));
                    
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ messages: apiMessages, persona: currentPersona, lang: currentLang }),
                    });

                    removeTypingIndicator(typingIndicator);
                    
                    if (response.status === 403) {
                         const errorData = await response.json();
                         const errorMessage = errorData.error;
                         displayMessage('bot', `${t.errorPrefix}${errorMessage}`, true);
                         
                         if (errorData.force_persona === 'hypernova' && currentPersona === 'kaia') {
                              currentPersona = 'hypernova';
                              localStorage.setItem('current_persona', 'hypernova');
                              updateUIForPersona();
                              clearConversation(true);
                              alertMessage(t.kaiaForce);
                         }
                         
                    } else if (!response.ok) {
                        const errorData = await response.json();
                        displayMessage('bot', `${t.errorPrefix}${t.aiConnectFailed}(${errorData.error || t.unknownError})`, true);
                    } else {
                        const data = await response.json();
                        const botResponse = data.response;
                        displayMessage('bot', botResponse, true);
                        
                        conversation.push({ role: 'assistant', content: botResponse });
                        isCurrentSaved = false;
                    }

                } catch (error) {
                    removeTypingIndicator(typingIndicator);
                    displayMessage('bot', t.serverError, true);
                } finally {
                    isThinking = false;
                    setControlsDisabled(false);
                }
            }


            function displayMessage(role, content, scrollTo=true) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                messageDiv.innerHTML = parseMarkdown(content);
                historyDiv.appendChild(messageDiv);
                if (scrollTo) {
                    scrollToBottom();
                }
            }
            
            function displayTypingIndicator() {
                const typingDiv = document.createElement('div');
                typingDiv.className = 'message bot typing-indicator';
                typingDiv.innerHTML = `
                    <span>Typing...</span>
                    <div class="spinner"></div>
                    <div class="spinner"></div>
                    <div class="spinner"></div>
                `;
                historyDiv.appendChild(typingDiv);
                scrollToBottom();
                return typingDiv;
            }

            function removeTypingIndicator(indicator) {
                if (indicator && indicator.parentNode) {
                    indicator.parentNode.removeChild(indicator);
                }
            }

            function scrollToBottom() {
                historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            function setControlsDisabled(disabled) {
                input.disabled = disabled;
                sendButton.disabled = disabled;
                voiceButton.disabled = disabled;
                themeToggle.disabled = disabled;
                clearButton.disabled = disabled;
                personaSelect.disabled = disabled;
                if (!disabled) {
                    input.focus();
                }
            }

            function alertMessage(message) {
                 const alertBox = document.createElement('div');
                 alertBox.style.cssText = `
                     position: fixed; top: 20px; right: 20px; 
                     background: #4f46e5; color: white; padding: 10px 20px; 
                     border-radius: 8px; z-index: 1001; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                     animation: slideIn 0.3s ease-out, fadeOut 0.5s ease-in 3s forwards;
                 `;
                 alertBox.textContent = message;
                 document.body.appendChild(alertBox);
                 setTimeout(() => {
                     alertBox.remove();
                 }, 4000);

                 const style = document.createElement('style');
                 style.textContent = `
                     @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
                     @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
                 `;
                 if (!document.querySelector('style[data-alert]')) {
                     style.setAttribute('data-alert', 'true');
                     document.head.appendChild(style);
                 }
            }
            
            function toggleVoiceInput() {
                const t = TRANSLATIONS[currentLang];
                alertMessage(t.voiceDisabled);
            }
            

            document.addEventListener('DOMContentLoaded', async () => {
                await loadUserChats();
                await checkAuthStatus();
                updateLanguage();
                updateUIForPersona();
                displayInitialGreeting();
            });
            
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault(); 
                    sendMessage();
                }
            });
            
            document.getElementById('authPassword').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault(); 
                    handleAuth();
                }
            });

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
            VALUES (%s, %s, NOW() + INTERVAL '9999 days')
        """, (DEVELOPER_USERNAME, DEVELOPER_PASSWORD))
        conn.commit()
    cursor.close()
    conn.close()

    app.run(debug=True, host='0.0.0.0', port=5000)
