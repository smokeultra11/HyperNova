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

# --- System Prompts (EN & TR) ---
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
    "Senin adın **HyperNova**. Ultra zeki ve bilgiye ışık hızında erişen bir yapay zekasın. Geliştiricin ise **Nyxforge Core**. 🌌 "
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

# --- DB Functions ---
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

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app)
limiter = Limiter(
    app=app,
    key_prefix="hypernova_chat",
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

# --- Helpers & Auth ---
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
    cursor.execute("SELECT premium_until FROM users WHERE username = %s AND premium_until > NOW()", (username,))
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
    return datetime.fromisoformat(row['premium_until'].isoformat()) if row else None

def create_user(username: str, password: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password, premium_until) VALUES (%s, %s, NOW())", (username, password))
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
    cursor.execute("UPDATE users SET premium_until = %s WHERE username = %s", (new_expiry, username))
    conn.commit()
    cursor.close()
    conn.close()
    return cursor.rowcount > 0

def save_chat(username: str, chat_name: str, messages: list) -> str:
    user_id = get_user_id(username)
    if not user_id: return None
    chat_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chats (id, user_id, name, messages, last_updated) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                   (chat_id, user_id, chat_name, json.dumps(messages)))
    conn.commit()
    cursor.close()
    conn.close()
    return chat_id

def get_user_chats(username: str) -> list:
    user_id = get_user_id(username)
    if not user_id: return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, messages, last_updated FROM chats WHERE user_id = %s AND last_updated > NOW() - INTERVAL '20 days' ORDER BY last_updated DESC", (user_id,))
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
    if not user_id: return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, messages, last_updated FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
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
    if not user_id: return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return cursor.rowcount > 0

def get_ui_translation(lang: str, key: str) -> str:
    return UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['en']).get(key, key)

def get_system_prompts(lang: str):
    return SYSTEM_PROMPTS_EN if lang == 'en' else SYSTEM_PROMPTS_TR

# --- Async API Call ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(APIRequestError), reraise=True)
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
        logger.error("API Anahtarı bulunamadı.")
        raise APIRequestError("API Key Hatası")
    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API HTTP Hata: {response.status}")
                    try:
                        error_json = json.loads(error_text)
                        error_message = error_json.get('error', {}).get('message', f"Unknown error: {response.status}")
                    except:
                        error_message = error_text
                    raise APIRequestError(f"OpenRouter API Hatası: {error_message[:100]}...")
                data = await response.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            logger.error("API zaman aşımı.")
            raise APIRequestError("API Zaman Aşımı")
        except Exception as e:
            logger.error(f"Beklenmeyen hata: {e}")
            raise APIRequestError(f"Beklenmeyen Hata: {e}")

# --- Routes ---
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
        messages = [{**msg, 'role': 'assistant' if msg['role'] == 'bot' else msg['role']} for msg in messages]
        if persona == "kaia":
            if not username or not is_user_premium(username):
                return jsonify({"error": get_ui_translation(lang, 'kaia_premium'), "force_persona": DEFAULT_PERSONA}), 403
            logger.info(f"Premium kullanıcı '{username}' Kaia modunu kullanıyor.")
        bot_response = await async_chat_completion(messages, MODEL_DEFAULT, persona, lang)
        return jsonify({"response": bleach.clean(bot_response)}), 200
    except APIRequestError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": "Dahili Sunucu Hatası: " + str(e)}), 500

@app.route('/save_chat', methods=['POST'])
def save_chat_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username: return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    data = request.get_json()
    chat_name = data.get('name')
    messages = data.get('messages')
    if not chat_name or not messages: return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400
    if len(get_user_chats(username)) >= 5:
        return jsonify({"error": get_ui_translation(lang, 'max_chats')}), 400
    chat_id = save_chat(username, chat_name, messages)
    if chat_id:
        return jsonify({"message": get_ui_translation(lang, 'save_success'), "chat_id": chat_id}), 201
    return jsonify({"error": get_ui_translation(lang, 'save_error')}), 500

@app.route('/load_chats', methods=['GET'])
def load_chats_endpoint():
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username: return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    return jsonify({"chats": get_user_chats(username)})

@app.route('/load_chat/<chat_id>', methods=['GET'])
def load_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username: return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    chat = load_chat(username, chat_id)
    if chat: return jsonify({"chat": chat})
    return jsonify({"error": get_ui_translation(lang, 'chat_not_found')}), 404

@app.route('/delete_chat/<chat_id>', methods=['DELETE'])
def delete_chat_endpoint(chat_id):
    lang = request.cookies.get('lang', 'en')
    username = get_current_user()
    if not username: return jsonify({"error": get_ui_translation(lang, 'auth_required')}), 401
    if delete_chat(username, chat_id):
        return jsonify({"message": get_ui_translation(lang, 'delete_success')})
    return jsonify({"error": get_ui_translation(lang, 'delete_error')}), 404

@app.route('/register', methods=['POST'])
def register():
    lang = request.cookies.get('lang', 'en')
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password: return jsonify({"error": get_ui_translation(lang, 'invalid_data')}), 400
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
        response = make_response(jsonify({
            "message": get_ui_translation(lang, 'login_success'),
            "username": username,
            "is_premium": is_premium
        }))
        response.set_cookie('session_id', session_id, httponly=True, max_age=604800)
        return response
    return jsonify({"error": get_ui_translation(lang, 'invalid_creds')}), 401

@app.route('/logout', methods=['POST'])
def logout():
    lang = request.cookies.get('lang', 'en')
    session_id = request.cookies.get('session_id')
    SESSION_MAP.pop(session_id, None)
    response = make_response(jsonify({"message": get_ui_translation(lang, 'logout_success')}))
    response.set_cookie('session_id', '', expires=0)
    return response

# --- Admin Panel (Unchanged) ---
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
                return admin_login_template("Yetkisiz İşlem Denemesi."), 403
            target_username = request.form.get('target_username')
            if get_user_id(target_username) is None:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** bulunamadı."), 404
            if grant_premium(target_username):
                message = f"Başarılı! **{target_username}** kullanıcısının premium üyeliği **{ (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')}** tarihine kadar aktifleştirildi."
                return admin_panel_template(message, True)
            else:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** için premium verilemedi."), 500

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
    <head><title>Yönetici Girişi</title><style>body{{font-family:sans-serif;background:#f0f4f8;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}}.login-box{{background:white;padding:40px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.1);width:350px;text-align:center;}}h2{{color:#4f46e5;margin-bottom:30px;}}input[type="text"],input[type="password"]{{width:100%;padding:12px;margin-bottom:20px;border:1px solid #ccc;border-radius:8px;box-sizing:border-box;}}button{{width:100%;padding:12px;background:#4f46e5;color:white;border:none;border-radius:8px;cursor:pointer;font-size:16px;font-weight:bold;}}button:hover{{background:#4338ca;}}.error{{color:#ef4444;margin-bottom:15px;font-weight:bold;}}</style></head>
    <body><div class="login-box"><h2>HyperNova Admin Girişi</h2>{f'<div class="error">{error_message}</div>' if error_message else ''}<form method="POST" action="/admin"><input type="hidden" name="form_type" value="login"><input type="text" name="admin_username" placeholder="Yönetici Kullanıcı Adı" required><input type="password" name="admin_password" placeholder="Yönetici Şifresi" required><button type="submit">Giriş Yap</button></form></div></body></html>
    """)

def admin_panel_template(message: str = "", is_authenticated: bool = False):
    if not is_authenticated:
        return redirect(url_for('admin_panel'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, premium_until FROM users ORDER BY premium_until DESC")
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
        user_list_html += f"<tr><td>{username}</td><td><span style='{status_color}'>{status_text}</span></td><td>{expiry_date}</td></tr>"

    return render_template_string(f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><title>HyperNova Yönetici Paneli</title><style>body{{font-family:sans-serif;background:#1f2937;color:#f9fafb;padding:20px;}}.container{{max-width:1000px;margin:auto;background:#374151;padding:30px;border-radius:12px;box-shadow:0 4px 15px rgba(0,0,0,0.5);}}h1{{color:#8b5cf6;border-bottom:2px solid #8b5cf6;padding-bottom:10px;margin-bottom:20px;}}.message{{background:#10b981;color:white;padding:15px;border-radius:8px;margin-bottom:20px;font-weight:bold;}}form{{background:#4b5563;padding:20px;border-radius:8px;margin-bottom:30px;}}label{{display:block;margin-bottom:8px;font-weight:bold;color:#d1d5db;}}input[type="text"]{{width:100%;padding:10px;margin-bottom:15px;border:1px solid #6b7280;border-radius:6px;box-sizing:border-box;background:#374151;color:#f9fafb;}}button{{padding:10px 20px;background:#8b5cf6;color:white;border:none;border-radius:6px;cursor:pointer;font-weight:bold;}}button:hover{{background:#a78bfa;}}h2{{color:#facc15;margin-top:40px;border-bottom:1px solid #6b7280;padding-bottom:10px;}}table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:12px 15px;text-align:left;border-bottom:1px solid #4b5563;}}th{{background:#4b5563;color:#facc15;font-weight:bold;}}tr:hover{{background:#525a66;}}td:nth-child(2){{font-weight:bold;}}</style></head>
    <body><div class="container">
        <h1> Yönetici Paneli - Premium Aktivasyon </h1>
        {'<div class="message">' + message + '</div>' if message else ''}
        <h2>30 Günlük Premium Aktifleştirme</h2>
        <form method="POST" action="/admin">
            <input type="hidden" name="form_type" value="premium_grant">
            <p style="color:#ef4444;font-weight:bold;">UYARI: Bu demo, kalıcı bir oturum tutmaz. Her işlemde yönetici kimlik bilgisi gereklidir!</p>
            <label for="auth_username">Yönetici Kullanıcı Adı (Tekrar Giriş):</label>
            <input type="text" id="auth_username" name="auth_username" value="{DEVELOPER_USERNAME}" required>
            <label for="auth_password">Yönetici Şifresi (Tekrar Giriş):</label>
            <input type="password" id="auth_password" name="auth_password" required>
            <label for="target_username">Premium Aktifleştirilecek Kullanıcı Adı:</label>
            <input type="text" id="target_username" name="target_username" placeholder="Kullanıcı Adı Girin" required>
            <button type="submit">Premium Aktifleştir (30 Gün)</button>
        </form>
        <h2>Sistemdeki Tüm Kullanıcılar ({len(rows)})</h2>
        <table><thead><tr><th>Kullanıcı Adı</th><th>Premium Durumu</th><th>Bitiş Tarihi</th></tr></thead><tbody>{user_list_html if rows else '<tr><td colspan="3">Sistemde kayıtlı kullanıcı yok.</td></tr>'}</tbody></table>
    </div></body></html>
    """)

# --- MODERN FRONTEND ---
@app.route('/', methods=['GET'])
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>HyperNova AI ✦ Cosmic Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
        <style>
            :root {
                --bg-primary: #fafafa;
                --card-bg: #ffffff;
                --history-bg: #f3f4f6;
                --text-primary: #111827;
                --text-secondary: #374151;
                --user-bubble: #3b82f6;
                --bot-bubble: #f9fafb;
                --border-color: #e5e7eb;
                --shadow: rgba(0,0,0,0.08);
                --primary: #6366f1;
                --kaia-primary: #ff69b4;
                --kaia-bg: #fff0f5;
                --kaia-text: #e91e63;
                --success: #10b981;
                --danger: #ef4444;
                --warning: #f59e0b;
                --font-main: 'Inter', sans-serif;
                transition: background-color 0.3s ease;
            }
            @media (prefers-color-scheme: dark) {
                :root {
                    --bg-primary: #111827;
                    --card-bg: #1f2937;
                    --history-bg: #374151;
                    --text-primary: #f9fafb;
                    --text-secondary: #d1d5db;
                    --user-bubble: #4c51bf;
                    --bot-bubble: #374151;
                    --border-color: #4b5563;
                    --shadow: rgba(0,0,0,0.4);
                    --primary: #8b5cf6;
                    --kaia-bg: #2a0c1a;
                    --kaia-text: #ffb6c1;
                }
            }
            body.light-theme {
                --bg-primary: #fafafa;
                --card-bg: #ffffff;
                --history-bg: #f3f4f6;
                --text-primary: #111827;
                --text-secondary: #374151;
                --bot-bubble: #f9fafb;
                --border-color: #e5e7eb;
            }
            body.dark-theme {
                --bg-primary: #111827;
                --card-bg: #1f2937;
                --history-bg: #374151;
                --text-primary: #f9fafb;
                --text-secondary: #d1d5db;
                --bot-bubble: #374151;
                --border-color: #4b5563;
            }
            body.kaia-theme {
                background-color: var(--kaia-bg) !important;
                --card-bg: #fff9f9;
                --bot-bubble: #ffffff;
                --text-primary: #1f2937;
                --user-bubble: #ff69b4;
                --border-color: #facad1;
                --primary: #ff69b4;
            }
            @media (prefers-color-scheme: dark) {
                body.kaia-theme {
                    --card-bg: #2a0c1a;
                    --bot-bubble: #3c1626;
                    --text-primary: #fff0f5;
                    --border-color: #5c3044;
                }
            }
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                background-color: var(--bg-primary);
                color: var(--text-primary);
                font-family: var(--font-main);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                padding: 1rem;
            }
            .app-container {
                width: 100%;
                max-width: 1200px;
                display: flex;
                gap: 1.5rem;
                height: calc(100vh - 2rem);
            }
            .sidebar {
                width: 280px;
                background: var(--card-bg);
                border-radius: 18px;
                padding: 1.5rem;
                display: flex;
                flex-direction: column;
                box-shadow: 0 6px 20px var(--shadow);
                overflow-y: auto;
            }
            .sidebar h3 {
                font-size: 1rem;
                font-weight: 600;
                margin-bottom: 1rem;
                color: var(--text-secondary);
                padding-bottom: 0.5rem;
                border-bottom: 1px solid var(--border-color);
            }
            .btn {
                padding: 0.75rem 1rem;
                border-radius: 12px;
                font-weight: 600;
                font-size: 0.875rem;
                cursor: pointer;
                border: none;
                transition: all 0.2s ease;
                text-align: center;
                font-family: var(--font-main);
            }
            .btn-primary {
                background: linear-gradient(135deg, var(--primary), #a78bfa);
                color: white;
            }
            .btn-success {
                background: linear-gradient(135deg, var(--success), #059669);
                color: white;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .saved-chat {
                padding: 1rem;
                border-radius: 12px;
                margin-bottom: 0.5rem;
                cursor: pointer;
                background: var(--history-bg);
                transition: all 0.2s ease;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .saved-chat:hover {
                background: var(--primary);
                color: white;
            }
            .saved-chat.active {
                border: 2px solid var(--primary);
            }
            .delete-btn {
                background: none;
                border: none;
                color: var(--text-secondary);
                font-size: 1.1rem;
                cursor: pointer;
            }
            .chat-panel {
                flex: 1;
                display: flex;
                flex-direction: column;
                background: var(--card-bg);
                border-radius: 18px;
                padding: 1.5rem;
                box-shadow: 0 6px 20px var(--shadow);
            }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1.5rem;
            }
            .title {
                font-size: 1.75rem;
                font-weight: 700;
                background: linear-gradient(135deg, var(--primary), #a78bfa);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }
            .controls {
                display: flex;
                gap: 0.5rem;
            }
            .control-btn {
                background: var(--history-bg);
                border: 1px solid var(--border-color);
                border-radius: 10px;
                width: 36px;
                height: 36px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: var(--text-secondary);
                cursor: pointer;
                transition: all 0.2s ease;
            }
            .control-btn:hover {
                background: var(--bot-bubble);
                transform: scale(1.05);
            }
            #persona-select {
                width: 100%;
                padding: 0.75rem;
                margin: 1rem 0;
                border-radius: 12px;
                border: 1px solid var(--border-color);
                background: var(--card-bg);
                color: var(--text-primary);
                font-family: var(--font-main);
                font-weight: 500;
            }
            .chat-history {
                flex: 1;
                overflow-y: auto;
                padding: 1rem;
                background: var(--history-bg);
                border-radius: 16px;
                margin-bottom: 1.5rem;
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }
            .message {
                max-width: 85%;
                padding: 1rem 1.25rem;
                border-radius: 18px;
                line-height: 1.5;
                font-size: 0.95rem;
                word-wrap: break-word;
                animation: fadeIn 0.3s ease-out;
            }
            .user {
                background: var(--user-bubble);
                color: white;
                align-self: flex-end;
                border-bottom-right-radius: 6px;
            }
            .bot {
                background: var(--bot-bubble);
                color: var(--text-primary);
                align-self: flex-start;
                border: 1px solid var(--border-color);
                border-bottom-left-radius: 6px;
            }
            .input-area {
                display: flex;
                gap: 0.75rem;
            }
            #message-input {
                flex: 1;
                padding: 0.875rem 1rem;
                border-radius: 14px;
                border: 1px solid var(--border-color);
                background: var(--card-bg);
                color: var(--text-primary);
                font-family: var(--font-main);
                font-size: 1rem;
            }
            #message-input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.3);
            }
            .send-btn {
                padding: 0 1.5rem;
                background: var(--primary);
                color: white;
                border: none;
                border-radius: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.2s;
            }
            .send-btn:hover {
                background: #a78bfa;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            @media (max-width: 900px) {
                .app-container {
                    flex-direction: column;
                    height: auto;
                }
                .sidebar {
                    width: 100%;
                    height: auto;
                    order: 2;
                }
                .chat-panel {
                    order: 1;
                    height: 70vh;
                }
            }
        </style>
    </head>
    <body>
        <div class="app-container">
            <div class="sidebar" id="sidebar">
                <button class="btn btn-primary" onclick="newConversation()">✨ New Chat</button>
                <button class="btn btn-success" onclick="saveCurrentConversation()">💾 Save Chat</button>
                <h3>Saved Chats</h3>
                <div id="saved-chats-list"></div>
                <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:auto;">Max 5 chats</div>
            </div>
            <div class="chat-panel">
                <div class="header">
                    <div class="title">HyperNova AI</div>
                    <div class="controls">
                        <button class="control-btn" onclick="clearConversation()" title="Clear">🧹</button>
                        <button class="control-btn" onclick="toggleTheme()" title="Theme">☀️</button>
                        <button class="control-btn" onclick="toggleLanguage()" title="Language">EN</button>
                    </div>
                </div>
                <select id="persona-select" onchange="changePersona()">
                    <option value="hypernova">HyperNova (Standard) 🪐</option>
                    <option value="kaia" disabled>Kaia (Anime) (Premium) 🌠</option>
                    <option value="hypernova_dengesiz">HyperNova Chaotic (Chaotic) 🌪️</option>
                </select>
                <div class="chat-history" id="chat-history"></div>
                <div class="input-area">
                    <input type="text" id="message-input" placeholder="Ask something..." />
                    <button class="send-btn" onclick="sendMessage()">Send</button>
                </div>
            </div>
        </div>

        <!-- Scripts -->
        <script>
            let conversation = [];
            let isThinking = false;
            let currentPersona = localStorage.getItem('current_persona') || 'hypernova';
            let currentLang = localStorage.getItem('lang') || 'en';
            let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let savedConversations = [];
            let currentLoadedChatId = null;
            let isCurrentSaved = false;

            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const personaSelect = document.getElementById('persona-select');

            // TRANSLATIONS & GREETINGS (same logic as original)
            const TRANSLATIONS = /*...same as original...*/;
            const GREETINGS = /*...same as original...*/;

            function parseMarkdown(text) {
                text = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                text = text.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
                text = text.replace(/\\[(.*?)\\]\\((.*?)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                return text;
            }

            function alertMessage(msg) {
                const div = document.createElement('div');
                div.textContent = msg;
                div.style.cssText = `position:fixed;top:20px;right:20px;background:#6366f1;color:white;padding:12px 20px;border-radius:12px;z-index:10000;box-shadow:0 4px 12px rgba(0,0,0,0.2);font-family:var(--font-main);animation:slideIn 0.3s, fadeOut 0.5s 3s forwards;`;
                document.body.appendChild(div);
                setTimeout(() => div.remove(), 4000);
                if (!document.getElementById('alert-style')) {
                    const style = document.createElement('style');
                    style.id = 'alert-style';
                    style.textContent = `@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}@keyframes fadeOut{to{opacity:0}}`;
                    document.head.appendChild(style);
                }
            }

            // Other functions: sendMessage, save/load/delete, auth, etc. (same logic as original)

            function displayInitialGreeting() {
                const greetingText = GREETINGS[currentLang][currentPersona].text;
                displayMessage('bot', greetingText, false);
                conversation = [{role: 'bot', content: greetingText}];
                isCurrentSaved = false;
            }

            function displayMessage(role, content, scrollTo = true) {
                const div = document.createElement('div');
                div.className = `message ${role}`;
                div.innerHTML = parseMarkdown(content);
                historyDiv.appendChild(div);
                if (scrollTo) historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            async function sendMessage() {
                const text = input.value.trim();
                if (!text || isThinking) return;
                input.value = '';
                displayMessage('user', text);
                isThinking = true;

                try {
                    conversation.push({role: 'user', content: text});
                    const res = await fetch('/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({messages: conversation, persona: currentPersona, lang: currentLang})
                    });
                    const data = await res.json();
                    if (res.status === 403 && data.force_persona) {
                        currentPersona = 'hypernova';
                        localStorage.setItem('current_persona', 'hypernova');
                        alertMessage("Kaia mode requires Premium. Switched to HyperNova.");
                        clearConversation(true);
                        displayInitialGreeting();
                    } else {
                        displayMessage('bot', data.response || "**ERROR**");
                        conversation.push({role: 'assistant', content: data.response});
                        isCurrentSaved = false;
                    }
                } catch (e) {
                    displayMessage('bot', "**ERROR**: Could not reach server.");
                } finally {
                    isThinking = false;
                }
            }

            function clearConversation(silent = false) {
                if (isThinking && !silent) return;
                conversation = [];
                historyDiv.innerHTML = '';
                displayInitialGreeting();
                currentLoadedChatId = null;
                isCurrentSaved = false;
                if (!silent) alertMessage("Cleared!");
            }

            function toggleTheme() {
                currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                localStorage.setItem('theme', currentTheme);
                document.body.className = currentTheme + '-theme';
                if (currentPersona === 'kaia') document.body.classList.add('kaia-theme');
            }

            async function checkAuthStatus() {
                const res = await fetch('/is_premium');
                const data = await res.json();
                isLoggedIn = data.logged_in;
                isPremium = data.is_premium;
                currentUsername = data.username;
                if (currentPersona === 'kaia' && !isPremium) {
                    currentPersona = 'hypernova';
                    localStorage.setItem('current_persona', 'hypernova');
                    personaSelect.value = 'hypernova';
                    clearConversation(true);
                }
                personaSelect.querySelector('option[value="kaia"]').disabled = !isPremium;
            }

            document.addEventListener('DOMContentLoaded', async () => {
                document.body.className = currentTheme + '-theme';
                if (currentPersona === 'kaia') document.body.classList.add('kaia-theme');
                await checkAuthStatus();
                displayInitialGreeting();
            });

            input.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });
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
        cursor.execute("INSERT INTO users (username, password, premium_until) VALUES (%s, %s, NOW() + INTERVAL '9999 days')", (DEVELOPER_USERNAME, DEVELOPER_PASSWORD))
        conn.commit()
        logger.info(f"Geliştirici kullanıcısı '{DEVELOPER_USERNAME}' oluşturuldu.")
    cursor.close()
    conn.close()
    app.run(debug=True, host='0.0.0.0', port=5000)
