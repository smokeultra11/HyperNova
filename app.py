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
MODEL_DEFAULT = "inclusionai/ling-2.6-flash"
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
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")
    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    error_text = await response.text()
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
            raise APIRequestError("API Zaman Aşımı")
        except Exception as e:
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
                return admin_login_template("Yetkisiz İşlem Denemesi."), 403
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
            .container {{ max-width: 1000px; margin: auto; background: #374151; padding: 30px; border-radius: 12px; }}
            h1 {{ color: #8b5cf6; border-bottom: 2px solid #8b5cf6; padding-bottom: 10px; }}
            .message {{ background: #10b981; color: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-weight: bold; }}
            form {{ background: #4b5563; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #d1d5db; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #6b7280; border-radius: 6px; box-sizing: border-box; background: #374151; color: #f9fafb; }}
            button {{ padding: 10px 20px; background-color: #8b5cf6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }}
            h2 {{ color: #facc15; margin-top: 40px; border-bottom: 1px solid #6b7280; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #4b5563; }}
            th {{ background-color: #4b5563; color: #facc15; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Yönetici Paneli - Premium Aktivasyon</h1>
            {'<div class="message">' + message + '</div>' if message else ''}
            <h2>30 Günlük Premium Aktifleştirme</h2>
            <form method="POST" action="/admin">
                <input type="hidden" name="form_type" value="premium_grant">
                <label>Yönetici Kullanıcı Adı:</label>
                <input type="text" name="auth_username" value="{DEVELOPER_USERNAME}" required>
                <label>Yönetici Şifresi:</label>
                <input type="password" name="auth_password" required>
                <label>Premium Aktifleştirilecek Kullanıcı Adı:</label>
                <input type="text" name="target_username" placeholder="Kullanıcı Adı" required>
                <button type="submit">Premium Aktifleştir (30 Gün)</button>
            </form>
            <h2>Tüm Kullanıcılar ({len(rows) if rows else 0})</h2>
            <table>
                <thead><tr><th>Kullanıcı Adı</th><th>Premium</th><th>Bitiş</th></tr></thead>
                <tbody>{user_list_html if rows else '<tr><td colspan="3">Kayıtlı kullanıcı yok.</td></tr>'}</tbody>
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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@200;300;400;500;600;700;800&family=Nunito:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        /* ═══════════════════════════════════════
           DESIGN TOKENS — NEO-COSMIC DARK LUXURY
           ═══════════════════════════════════════ */
        :root {
            --space-900: #030711;
            --space-800: #060d1a;
            --space-700: #0a1428;
            --space-600: #0f1d3a;
            --space-500: #162340;

            --glass-bg: rgba(10, 18, 40, 0.75);
            --glass-border: rgba(100, 120, 220, 0.18);
            --glass-border-hover: rgba(120, 140, 255, 0.35);

            --accent: #7c6fff;
            --accent-bright: #a48fff;
            --accent-glow: rgba(124, 111, 255, 0.35);
            --accent-electric: #4fc3f7;
            --accent-electric-glow: rgba(79, 195, 247, 0.2);

            --text-primary: #dde4f8;
            --text-secondary: rgba(210, 220, 248, 0.62);
            --text-muted: rgba(180, 195, 235, 0.35);

            --user-from: #5b50e8;
            --user-to: #8b5cf6;
            --bot-bg: rgba(14, 22, 50, 0.88);

            --kaia-accent: #ff6ea8;
            --kaia-glow: rgba(255, 110, 168, 0.3);
            --kaia-bot-bg: rgba(35, 10, 28, 0.88);

            --chaos-accent: #ff4d4d;
            --chaos-glow: rgba(255, 77, 77, 0.3);

            --sidebar-w: 260px;
            --radius-lg: 20px;
            --radius-md: 14px;
            --radius-sm: 10px;

            --transition: 0.28s cubic-bezier(0.4, 0, 0.2, 1);
        }

        /* LIGHT OVERRIDE */
        body.light-mode {
            --space-900: #eef1fa;
            --space-800: #e3e8f5;
            --space-700: #d6ddf0;
            --glass-bg: rgba(240, 244, 255, 0.85);
            --glass-border: rgba(100, 110, 200, 0.2);
            --text-primary: #1a1f3a;
            --text-secondary: rgba(40, 50, 100, 0.65);
            --text-muted: rgba(60, 70, 130, 0.4);
            --bot-bg: rgba(230, 236, 255, 0.9);
            --accent: #5b50e8;
            --accent-bright: #7c6fff;
        }

        /* ═══════════ RESET & BASE ═══════════ */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        html { height: 100%; }

        body {
            font-family: 'Nunito', sans-serif;
            background: var(--space-900);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden;
            transition: background var(--transition), color var(--transition);
        }

        /* ═══════════ STARFIELD CANVAS ═══════════ */
        #starfield {
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            opacity: 0.55;
        }
        body.light-mode #starfield { opacity: 0.12; }

        /* ═══════════ NEBULA BLOBS ═══════════ */
        .nebula {
            position: fixed;
            border-radius: 50%;
            filter: blur(80px);
            pointer-events: none;
            z-index: 0;
            animation: nebulaDrift 18s ease-in-out infinite alternate;
        }
        .nebula-1 {
            width: 500px; height: 500px;
            background: radial-gradient(circle, rgba(90,70,220,0.18) 0%, transparent 70%);
            top: -120px; left: -100px;
        }
        .nebula-2 {
            width: 400px; height: 400px;
            background: radial-gradient(circle, rgba(79,195,247,0.12) 0%, transparent 70%);
            bottom: -80px; right: -80px;
            animation-delay: -9s;
        }
        .nebula-3 {
            width: 300px; height: 300px;
            background: radial-gradient(circle, rgba(139,92,246,0.14) 0%, transparent 70%);
            top: 40%; left: 40%;
            animation-delay: -4s;
        }
        body.light-mode .nebula { opacity: 0.4; }
        @keyframes nebulaDrift {
            from { transform: translate(0, 0) scale(1); }
            to   { transform: translate(30px, 20px) scale(1.08); }
        }

        /* ═══════════ LAYOUT ═══════════ */
        .shell {
            position: relative;
            z-index: 1;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* ═══════════ SIDEBAR ═══════════ */
        .sidebar {
            width: var(--sidebar-w);
            flex-shrink: 0;
            background: var(--glass-bg);
            backdrop-filter: blur(24px) saturate(1.6);
            -webkit-backdrop-filter: blur(24px) saturate(1.6);
            border-right: 1px solid var(--glass-border);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: width var(--transition), transform var(--transition);
        }

        .sidebar-header {
            padding: 22px 18px 16px;
            border-bottom: 1px solid var(--glass-border);
        }

        .sidebar-logo {
            font-family: 'Exo 2', sans-serif;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 3px;
            text-transform: uppercase;
            color: var(--text-muted);
            margin-bottom: 14px;
        }

        .btn-new-chat {
            width: 100%;
            padding: 10px 14px;
            background: linear-gradient(135deg, var(--accent) 0%, var(--user-to) 100%);
            color: #fff;
            border: none;
            border-radius: var(--radius-sm);
            font-family: 'Nunito', sans-serif;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: opacity var(--transition), transform var(--transition), box-shadow var(--transition);
            box-shadow: 0 4px 18px var(--accent-glow);
        }
        .btn-new-chat:hover {
            opacity: 0.9;
            transform: translateY(-1px);
            box-shadow: 0 6px 24px var(--accent-glow);
        }

        .btn-save-chat {
            width: 100%;
            margin-top: 8px;
            padding: 9px 14px;
            background: rgba(79, 195, 247, 0.1);
            color: var(--accent-electric);
            border: 1px solid rgba(79, 195, 247, 0.25);
            border-radius: var(--radius-sm);
            font-family: 'Nunito', sans-serif;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: background var(--transition), border-color var(--transition), transform var(--transition);
        }
        .btn-save-chat:hover {
            background: rgba(79, 195, 247, 0.18);
            border-color: rgba(79, 195, 247, 0.45);
            transform: translateY(-1px);
        }

        .sidebar-section-title {
            padding: 16px 18px 8px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 2.5px;
            text-transform: uppercase;
            color: var(--text-muted);
            font-family: 'Exo 2', sans-serif;
        }

        .chats-list {
            flex: 1;
            overflow-y: auto;
            padding: 4px 10px;
        }
        .chats-list::-webkit-scrollbar { width: 4px; }
        .chats-list::-webkit-scrollbar-thumb {
            background: rgba(124, 111, 255, 0.3);
            border-radius: 4px;
        }

        .chat-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: background var(--transition), transform var(--transition);
            animation: slideInLeft 0.35s ease-out both;
            position: relative;
            overflow: hidden;
        }
        .chat-item::before {
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, var(--accent), var(--user-to));
            border-radius: 3px;
            opacity: 0;
            transition: opacity var(--transition);
        }
        .chat-item:hover { background: rgba(124, 111, 255, 0.1); transform: translateX(3px); }
        .chat-item:hover::before { opacity: 1; }
        .chat-item.active { background: rgba(124, 111, 255, 0.15); }
        .chat-item.active::before { opacity: 1; }

        .chat-item-icon {
            font-size: 14px;
            opacity: 0.7;
            flex-shrink: 0;
        }
        .chat-item-name {
            flex: 1;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            transition: color var(--transition);
        }
        .chat-item:hover .chat-item-name,
        .chat-item.active .chat-item-name { color: var(--text-primary); }

        .btn-delete-chat {
            background: none;
            border: none;
            font-size: 13px;
            cursor: pointer;
            padding: 3px 5px;
            border-radius: 6px;
            opacity: 0;
            transition: opacity var(--transition), background var(--transition);
            color: var(--text-muted);
            flex-shrink: 0;
        }
        .chat-item:hover .btn-delete-chat { opacity: 1; }
        .btn-delete-chat:hover { background: rgba(239,68,68,0.15); color: #ef4444; }

        .sidebar-footer {
            padding: 12px 18px;
            border-top: 1px solid var(--glass-border);
            font-size: 11px;
            color: var(--text-muted);
            text-align: center;
            font-style: italic;
        }

        /* ═══════════ MAIN CHAT AREA ═══════════ */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-width: 0;
            padding: 16px;
            gap: 12px;
        }

        /* ═══════════ TOPBAR ═══════════ */
        .topbar {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 18px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px) saturate(1.5);
            -webkit-backdrop-filter: blur(20px) saturate(1.5);
            border: 1px solid var(--glass-border);
            border-radius: var(--radius-lg);
            flex-shrink: 0;
        }

        .topbar-title {
            font-family: 'Exo 2', sans-serif;
            font-size: 20px;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent-bright) 0%, var(--accent-electric) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.3px;
            white-space: nowrap;
        }

        .topbar-spacer { flex: 1; }

        /* Auth status pill */
        .auth-pill {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            background: rgba(124,111,255,0.08);
            border: 1px solid rgba(124,111,255,0.2);
            border-radius: 50px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-secondary);
            white-space: nowrap;
        }
        .auth-pill .premium-badge {
            background: linear-gradient(135deg, #f59e0b, #fbbf24);
            color: #1a1200;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 7px;
            border-radius: 20px;
            letter-spacing: 0.5px;
        }

        .icon-btn {
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(124,111,255,0.08);
            border: 1px solid var(--glass-border);
            border-radius: 10px;
            cursor: pointer;
            font-size: 15px;
            transition: background var(--transition), border-color var(--transition), transform var(--transition);
            color: var(--text-secondary);
        }
        .icon-btn:hover {
            background: rgba(124,111,255,0.18);
            border-color: var(--glass-border-hover);
            transform: scale(1.08);
        }
        .icon-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

        .text-btn {
            padding: 6px 14px;
            border-radius: 8px;
            border: 1px solid var(--glass-border);
            background: rgba(124,111,255,0.08);
            color: var(--text-secondary);
            font-family: 'Nunito', sans-serif;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: background var(--transition), color var(--transition), border-color var(--transition);
            white-space: nowrap;
        }
        .text-btn:hover {
            background: rgba(124,111,255,0.18);
            border-color: var(--glass-border-hover);
            color: var(--text-primary);
        }
        .text-btn.accent {
            background: linear-gradient(135deg, var(--accent), var(--user-to));
            border-color: transparent;
            color: white;
            box-shadow: 0 2px 12px var(--accent-glow);
        }
        .text-btn.accent:hover { opacity: 0.88; }

        /* ═══════════ PERSONA SELECTOR ═══════════ */
        .persona-bar {
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }

        .persona-chip {
            flex: 1;
            padding: 8px 10px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--glass-border);
            background: var(--glass-bg);
            backdrop-filter: blur(12px);
            color: var(--text-secondary);
            font-family: 'Nunito', sans-serif;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            transition: all var(--transition);
            position: relative;
            overflow: hidden;
        }
        .persona-chip::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, var(--accent), var(--user-to));
            opacity: 0;
            transition: opacity var(--transition);
        }
        .persona-chip span { position: relative; z-index: 1; }
        .persona-chip:hover:not(:disabled) {
            border-color: var(--glass-border-hover);
            color: var(--text-primary);
        }
        .persona-chip.active { color: white; border-color: transparent; }
        .persona-chip.active::after { opacity: 1; }
        .persona-chip.kaia-active { color: white; border-color: transparent; }
        .persona-chip.kaia-active::after {
            background: linear-gradient(135deg, #ff6ea8, #c44b8a);
        }
        .persona-chip.chaos-active { color: white; border-color: transparent; }
        .persona-chip.chaos-active::after {
            background: linear-gradient(135deg, #ff4d4d, #c0392b);
        }
        .persona-chip:disabled { opacity: 0.45; cursor: not-allowed; }
        .persona-chip .lock { font-size: 10px; opacity: 0.7; }

        /* ═══════════ CHAT HISTORY ═══════════ */
        .chat-history {
            flex: 1;
            overflow-y: auto;
            padding: 18px 8px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            scroll-behavior: smooth;
            background: var(--glass-bg);
            backdrop-filter: blur(20px) saturate(1.4);
            -webkit-backdrop-filter: blur(20px) saturate(1.4);
            border: 1px solid var(--glass-border);
            border-radius: var(--radius-lg);
        }
        .chat-history::-webkit-scrollbar { width: 5px; }
        .chat-history::-webkit-scrollbar-thumb {
            background: rgba(124, 111, 255, 0.25);
            border-radius: 5px;
        }
        .chat-history::-webkit-scrollbar-thumb:hover {
            background: rgba(124, 111, 255, 0.45);
        }

        /* ═══════════ MESSAGES ═══════════ */
        .msg {
            display: flex;
            align-items: flex-end;
            gap: 10px;
            animation: msgIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
            max-width: 82%;
        }
        .msg.user { align-self: flex-end; flex-direction: row-reverse; }
        .msg.bot  { align-self: flex-start; }

        .msg-avatar {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            flex-shrink: 0;
            background: rgba(124,111,255,0.15);
            border: 1px solid rgba(124,111,255,0.25);
        }
        .msg.user .msg-avatar {
            background: linear-gradient(135deg, var(--user-from), var(--user-to));
            border: none;
        }

        .msg-bubble {
            padding: 11px 16px;
            border-radius: 18px;
            font-size: 14px;
            line-height: 1.65;
            font-weight: 400;
            word-break: break-word;
        }
        .msg.user .msg-bubble {
            background: linear-gradient(135deg, var(--user-from) 0%, var(--user-to) 100%);
            color: #fff;
            border-bottom-right-radius: 5px;
            box-shadow: 0 4px 20px rgba(91, 80, 232, 0.35);
        }
        .msg.bot .msg-bubble {
            background: var(--bot-bg);
            color: var(--text-primary);
            border: 1px solid var(--glass-border);
            border-bottom-left-radius: 5px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.2);
        }
        .msg-bubble strong { font-weight: 700; color: var(--accent-bright); }
        .msg.user .msg-bubble strong { color: rgba(255,255,255,0.9); }
        .msg-bubble em { font-style: italic; opacity: 0.88; }
        .msg-bubble a { color: var(--accent-electric); text-decoration: underline; }

        /* Kaia theme */
        body.kaia-mode .msg.bot .msg-bubble {
            background: var(--kaia-bot-bg);
            border-color: rgba(255, 110, 168, 0.2);
        }
        body.kaia-mode .msg.bot .msg-bubble strong { color: var(--kaia-accent); }
        body.kaia-mode .msg.user .msg-bubble {
            background: linear-gradient(135deg, #c2185b, var(--kaia-accent));
            box-shadow: 0 4px 20px var(--kaia-glow);
        }

        /* Chaos theme */
        body.chaos-mode .msg.bot .msg-bubble {
            border-color: rgba(255, 77, 77, 0.2);
        }
        body.chaos-mode .msg.bot .msg-bubble strong { color: var(--chaos-accent); }
        body.chaos-mode .msg.user .msg-bubble {
            background: linear-gradient(135deg, #b71c1c, var(--chaos-accent));
            box-shadow: 0 4px 20px var(--chaos-glow);
        }

        /* ═══════════ TYPING INDICATOR ═══════════ */
        .typing-dots {
            display: flex;
            gap: 5px;
            padding: 14px 18px;
            align-items: center;
        }
        .typing-dots span {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: var(--accent-bright);
            animation: typingBounce 1.4s ease-in-out infinite;
        }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }

        /* ═══════════ INPUT ROW ═══════════ */
        .input-row {
            display: flex;
            gap: 10px;
            align-items: center;
            padding: 10px 14px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px) saturate(1.5);
            -webkit-backdrop-filter: blur(20px) saturate(1.5);
            border: 1px solid var(--glass-border);
            border-radius: var(--radius-lg);
            flex-shrink: 0;
            transition: border-color var(--transition);
        }
        .input-row:focus-within {
            border-color: rgba(124, 111, 255, 0.45);
            box-shadow: 0 0 0 3px rgba(124, 111, 255, 0.1);
        }

        #message-input {
            flex: 1;
            background: none;
            border: none;
            outline: none;
            color: var(--text-primary);
            font-family: 'Nunito', sans-serif;
            font-size: 14px;
            font-weight: 500;
            padding: 6px 0;
            resize: none;
            height: 24px;
            max-height: 96px;
            line-height: 1.5;
            caret-color: var(--accent);
        }
        #message-input::placeholder { color: var(--text-muted); }
        #message-input:disabled { opacity: 0.5; }

        .input-divider {
            width: 1px;
            height: 22px;
            background: var(--glass-border);
            flex-shrink: 0;
        }

        .send-btn {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            border: none;
            background: linear-gradient(135deg, var(--accent), var(--user-to));
            color: white;
            font-size: 16px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: opacity var(--transition), transform var(--transition), box-shadow var(--transition);
            box-shadow: 0 3px 14px var(--accent-glow);
            flex-shrink: 0;
        }
        .send-btn:hover:not(:disabled) {
            opacity: 0.88;
            transform: scale(1.06);
            box-shadow: 0 5px 20px var(--accent-glow);
        }
        .send-btn:disabled { opacity: 0.35; cursor: not-allowed; transform: none; box-shadow: none; }

        /* ═══════════ MODAL ═══════════ */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(3, 7, 17, 0.72);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 100;
            display: none;
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.open { display: flex; }

        .modal-card {
            background: rgba(10, 16, 38, 0.97);
            border: 1px solid rgba(124, 111, 255, 0.25);
            border-radius: var(--radius-lg);
            padding: 36px 32px;
            width: 380px;
            max-width: 94vw;
            box-shadow: 0 24px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(124,111,255,0.08);
            animation: modalIn 0.32s cubic-bezier(0.34, 1.56, 0.64, 1) both;
        }

        .modal-logo {
            font-family: 'Exo 2', sans-serif;
            font-size: 22px;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent-bright), var(--accent-electric));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            text-align: center;
            margin-bottom: 6px;
        }
        .modal-subtitle {
            text-align: center;
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 28px;
        }

        .modal-input {
            width: 100%;
            padding: 12px 14px;
            margin-bottom: 12px;
            background: rgba(124,111,255,0.06);
            border: 1px solid rgba(124,111,255,0.18);
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-family: 'Nunito', sans-serif;
            font-size: 14px;
            outline: none;
            transition: border-color var(--transition), box-shadow var(--transition);
        }
        .modal-input:focus {
            border-color: rgba(124,111,255,0.5);
            box-shadow: 0 0 0 3px rgba(124,111,255,0.1);
        }
        .modal-input::placeholder { color: var(--text-muted); }

        .modal-btn-primary {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, var(--accent), var(--user-to));
            color: white;
            border: none;
            border-radius: var(--radius-sm);
            font-family: 'Nunito', sans-serif;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: opacity var(--transition), box-shadow var(--transition);
            box-shadow: 0 4px 18px var(--accent-glow);
            margin-bottom: 10px;
        }
        .modal-btn-primary:hover { opacity: 0.88; box-shadow: 0 6px 24px var(--accent-glow); }

        .modal-btn-secondary {
            width: 100%;
            padding: 11px;
            background: rgba(124,111,255,0.08);
            color: var(--accent-bright);
            border: 1px solid rgba(124,111,255,0.22);
            border-radius: var(--radius-sm);
            font-family: 'Nunito', sans-serif;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: background var(--transition), border-color var(--transition);
        }
        .modal-btn-secondary:hover {
            background: rgba(124,111,255,0.16);
            border-color: rgba(124,111,255,0.4);
        }

        .modal-error {
            background: rgba(239,68,68,0.1);
            border: 1px solid rgba(239,68,68,0.25);
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 13px;
            color: #fca5a5;
            margin-bottom: 14px;
            display: none;
        }
        .modal-error.visible { display: block; }

        /* ═══════════ TOAST ═══════════ */
        .toast-container {
            position: fixed;
            top: 18px;
            right: 18px;
            z-index: 200;
            display: flex;
            flex-direction: column;
            gap: 8px;
            pointer-events: none;
        }
        .toast {
            background: rgba(10, 18, 42, 0.95);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(124,111,255,0.3);
            border-radius: 12px;
            padding: 12px 18px;
            color: var(--text-primary);
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            animation: toastIn 0.3s ease-out, toastOut 0.4s ease-in 3.5s forwards;
            max-width: 300px;
        }

        /* ═══════════ KEYFRAMES ═══════════ */
        @keyframes msgIn {
            from { opacity: 0; transform: translateY(12px) scale(0.97); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes typingBounce {
            0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
            30%            { transform: translateY(-6px); opacity: 1; }
        }
        @keyframes modalIn {
            from { opacity: 0; transform: scale(0.92) translateY(20px); }
            to   { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes toastIn {
            from { opacity: 0; transform: translateX(30px); }
            to   { opacity: 1; transform: translateX(0); }
        }
        @keyframes toastOut {
            from { opacity: 1; transform: translateX(0); }
            to   { opacity: 0; transform: translateX(30px); }
        }
        @keyframes slideInLeft {
            from { opacity: 0; transform: translateX(-12px); }
            to   { opacity: 1; transform: translateX(0); }
        }

        /* ═══════════ RESPONSIVE ═══════════ */
        @media (max-width: 768px) {
            :root { --sidebar-w: 0px; }
            .sidebar { position: fixed; left: 0; top: 0; bottom: 0; width: 260px; transform: translateX(-100%); z-index: 50; }
            .sidebar.open { transform: translateX(0); }
            .main { padding: 10px; }
            .topbar-title { font-size: 17px; }
        }
    </style>
</head>
<body>

<!-- Background layers -->
<canvas id="starfield"></canvas>
<div class="nebula nebula-1"></div>
<div class="nebula nebula-2"></div>
<div class="nebula nebula-3"></div>

<!-- Toast container -->
<div class="toast-container" id="toastContainer"></div>

<!-- Auth Modal -->
<div class="modal-overlay" id="authModal" onclick="handleModalOverlayClick(event)">
    <div class="modal-card">
        <div class="modal-logo">HyperNova AI</div>
        <div class="modal-subtitle" id="modalSubtitle">Sign in to your account</div>
        <div class="modal-error" id="authError"></div>
        <input class="modal-input" type="text" id="authUsername" placeholder="Username" autocomplete="username">
        <input class="modal-input" type="password" id="authPassword" placeholder="Password" autocomplete="current-password">
        <button class="modal-btn-primary" id="modalPrimaryBtn" onclick="handleAuth()">Login</button>
        <button class="modal-btn-secondary" id="modalSwitchBtn" onclick="switchAuthMode()">Don't have an account? Register</button>
    </div>
</div>

<!-- Shell -->
<div class="shell">

    <!-- SIDEBAR -->
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-logo">HyperNova</div>
            <button class="btn-new-chat" onclick="newConversation()">
                <span>✦</span> <span>New Chat</span>
            </button>
            <button class="btn-save-chat" id="saveChatBtn" onclick="saveCurrentConversation()">
                <span>💾</span> <span>Save Chat</span>
            </button>
        </div>
        <div class="sidebar-section-title" id="savedChatsLabel">Recent</div>
        <div class="chats-list" id="savedChatsList"></div>
        <div class="sidebar-footer" id="sidebarFooter">Max 5 saved chats</div>
    </aside>

    <!-- MAIN -->
    <main class="main">

        <!-- TOPBAR -->
        <div class="topbar">
            <div class="topbar-title" id="topbarTitle">HyperNova AI 🪐</div>
            <div class="topbar-spacer"></div>

            <!-- Auth pill -->
            <div class="auth-pill" id="authPill">
                <span id="userInfoText">Not logged in</span>
            </div>

            <!-- Auth buttons -->
            <div id="authBtns" style="display:flex;gap:6px;">
                <button class="text-btn" onclick="showModal('login')" id="btnLogin">Login</button>
                <button class="text-btn accent" onclick="showModal('register')" id="btnRegister">Register</button>
            </div>
            <button class="text-btn" id="btnLogout" style="display:none;" onclick="logout()">Logout</button>

            <!-- Icon buttons -->
            <button class="icon-btn" id="clearBtn" onclick="clearConversation()" title="Clear chat">🧹</button>
            <button class="icon-btn" id="themeBtn" onclick="toggleTheme()" title="Toggle theme">🌙</button>
            <button class="icon-btn" id="langBtn" onclick="toggleLanguage()" title="Language">EN</button>
        </div>

        <!-- PERSONA CHIPS -->
        <div class="persona-bar" id="personaBar">
            <button class="persona-chip active" data-persona="hypernova" onclick="selectPersona('hypernova')">
                <span>🪐 HyperNova</span>
            </button>
            <button class="persona-chip" data-persona="kaia" onclick="selectPersona('kaia')" disabled>
                <span>🌸 Kaia <span class="lock">🔒</span></span>
            </button>
            <button class="persona-chip" data-persona="hypernova_dengesiz" onclick="selectPersona('hypernova_dengesiz')">
                <span>🌪️ Chaotic</span>
            </button>
        </div>

        <!-- CHAT HISTORY -->
        <div class="chat-history" id="chatHistory"></div>

        <!-- INPUT ROW -->
        <div class="input-row" id="inputRow">
            <button class="icon-btn" id="voiceBtn" onclick="toggleVoiceInput()" title="Voice input" style="border:none;background:none;width:32px;height:32px;font-size:18px;flex-shrink:0;">🎙️</button>
            <div class="input-divider"></div>
            <input type="text" id="message-input" placeholder="Ask a cosmic question…">
            <button class="send-btn" id="sendBtn" onclick="sendMessage()">➤</button>
        </div>

    </main>
</div>

<script>
// ═══════════════════════════════════════════
//  STARFIELD
// ═══════════════════════════════════════════
(function() {
    const canvas = document.getElementById('starfield');
    const ctx = canvas.getContext('2d');
    let stars = [];
    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    function makeStars(n) {
        stars = Array.from({length: n}, () => ({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            r: Math.random() * 1.4 + 0.2,
            a: Math.random(),
            speed: Math.random() * 0.004 + 0.001,
            phase: Math.random() * Math.PI * 2
        }));
    }
    function draw(t) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        stars.forEach(s => {
            const alpha = s.a * (0.5 + 0.5 * Math.sin(t * s.speed + s.phase));
            ctx.beginPath();
            ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(200, 210, 255, ${alpha})`;
            ctx.fill();
        });
        requestAnimationFrame(draw);
    }
    resize();
    makeStars(160);
    window.addEventListener('resize', () => { resize(); makeStars(160); });
    requestAnimationFrame(draw);
})();

// ═══════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════
let conversation = [];
let isThinking = false;
let savedConversations = [];
let currentLoadedChatId = null;
let isCurrentSaved = false;
let isLoggedIn = false;
let isPremium = false;
let currentUsername = null;
let authMode = 'login';
let currentLang = localStorage.getItem('lang') || 'en';
let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
let currentPersona = localStorage.getItem('current_persona') || 'hypernova';

// ═══════════════════════════════════════════
//  TRANSLATIONS
// ═══════════════════════════════════════════
const T = {
    en: {
        newChat: 'New Chat', saveChat: '💾 Save Chat', recent: 'Recent',
        maxChats: 'Max 5 saved chats', send: 'Send', login: 'Login',
        register: 'Register', logout: 'Logout', welcome: 'Welcome, ',
        notLoggedIn: 'Not logged in', modalLoginTitle: 'Sign in to your account',
        modalRegisterTitle: 'Create an account', switchToRegister: "Don't have an account? Register",
        switchToLogin: 'Already have an account? Login', usernamePH: 'Username', passwordPH: 'Password',
        emptyCred: 'Username and password cannot be empty.', networkError: 'Network error. Try again.',
        authReqSave: 'Please log in to save conversations.', authReqLoad: 'Please log in to load conversations.',
        authReqDelete: 'Please log in to delete conversations.', chatsLoadError: 'Could not load chats: ',
        saveError: 'Save error: ', loadError: 'Load error: ', deleteError: 'Delete error: ',
        thinkingBusy: 'Please wait, AI is thinking… ⏳', voiceDisabled: 'Voice input is not available in this demo. 🎤',
        errorPrefix: '⚠️ ', aiConnectFailed: 'Could not reach AI. Please try again. ',
        unknownError: 'Unknown Error', serverError: '⚠️ Server unreachable. Check your connection.',
        kaiaForce: 'Kaia requires Premium — switching back to HyperNova.',
        newConvSavePrompt: 'Start new chat? Save current conversation first? (Cancel = keep current)',
        discardConfirm: 'Continue without saving?', newConvStarted: 'New conversation started ✦',
        clearConfirm: 'Clear conversation history?', cleared: 'History cleared. Starting fresh.',
        savePrompt: 'Name this conversation:', saveNoName: 'Please enter a name.',
        saveMinMsg: 'No messages yet. Send at least one message first.',
        saveMax: 'Max 5 chats reached. Delete one first.',
        saved: 'Saved: "', savedSuffix: '" 💾', loaded: ' loaded.',
        deleteConfirm: 'Delete this conversation?', deleted: 'Deleted 🗑️',
        changeConfirm: 'Switch to %s? History will be cleared. Continue?',
        modeChanged: 'Switched to ', modeChangedSuffix: '. New conversation started.',
        kaiaPremiumReq: 'Kaia mode is for ⭐ Premium subscribers only. Please upgrade.',
        welcomePremium: 'Premium active ✨', welcomeFree: 'Free plan — HyperNova available.',
        persona: { hypernova: '🪐 HyperNova', kaia: '🌸 Kaia 🔒', hypernova_dengesiz: '🌪️ Chaotic' },
        personaName: { hypernova: 'HyperNova', kaia: 'Kaia', hypernova_dengesiz: 'HyperNova Chaotic' }
    },
    tr: {
        newChat: 'Yeni Sohbet', saveChat: '💾 Kaydet', recent: 'Son Sohbetler',
        maxChats: 'Maks. 5 sohbet', send: 'Gönder', login: 'Giriş',
        register: 'Kayıt', logout: 'Çıkış', welcome: 'Hoş geldin, ',
        notLoggedIn: 'Giriş yapılmadı', modalLoginTitle: 'Hesabına giriş yap',
        modalRegisterTitle: 'Hesap oluştur', switchToRegister: 'Hesabın yok mu? Kayıt ol',
        switchToLogin: 'Hesabın var mı? Giriş yap', usernamePH: 'Kullanıcı Adı', passwordPH: 'Şifre',
        emptyCred: 'Kullanıcı adı ve şifre boş olamaz.', networkError: 'Ağ hatası. Tekrar dene.',
        authReqSave: 'Kaydetmek için giriş yap.', authReqLoad: 'Yüklemek için giriş yap.',
        authReqDelete: 'Silmek için giriş yap.', chatsLoadError: 'Sohbetler yüklenemedi: ',
        saveError: 'Kayıt hatası: ', loadError: 'Yükleme hatası: ', deleteError: 'Silme hatası: ',
        thinkingBusy: 'Lütfen bekle, AI düşünüyor… ⏳', voiceDisabled: 'Sesli giriş bu demoda aktif değil. 🎤',
        errorPrefix: '⚠️ ', aiConnectFailed: 'AI\'a ulaşılamadı. Tekrar dene. ',
        unknownError: 'Bilinmeyen Hata', serverError: '⚠️ Sunucuya ulaşılamadı.',
        kaiaForce: 'Kaia Premium gerektiriyor — HyperNova\'ya dönüldü.',
        newConvSavePrompt: 'Yeni sohbet başlatılsın mı? Önce kaydet? (İptal = devam)',
        discardConfirm: 'Kaydetmeden devam et?', newConvStarted: 'Yeni sohbet başlatıldı ✦',
        clearConfirm: 'Sohbet geçmişi silinsin mi?', cleared: 'Geçmiş silindi.',
        savePrompt: 'Sohbet adını girin:', saveNoName: 'Lütfen bir isim girin.',
        saveMinMsg: 'Henüz mesaj yok. Önce mesaj gönder.',
        saveMax: 'Maks. 5 sohbet. Önce birini sil.',
        saved: 'Kaydedildi: "', savedSuffix: '" 💾', loaded: ' yüklendi.',
        deleteConfirm: 'Bu sohbet silinsin mi?', deleted: 'Silindi 🗑️',
        changeConfirm: '%s moduna geçilsin mi? Geçmiş silinecek.',
        modeChanged: '', modeChangedSuffix: ' moduna geçildi. Yeni sohbet başladı.',
        kaiaPremiumReq: 'Kaia modu yalnızca ⭐ Premium üyeler içindir.',
        welcomePremium: 'Premium aktif ✨', welcomeFree: 'Ücretsiz plan — HyperNova kullanılabilir.',
        persona: { hypernova: '🪐 HyperNova', kaia: '🌸 Kaia 🔒', hypernova_dengesiz: '🌪️ Dengesiz' },
        personaName: { hypernova: 'HyperNova', kaia: 'Kaia', hypernova_dengesiz: 'HyperNova Dengesiz' }
    }
};

const GREETINGS = {
    en: {
        hypernova: { text: "**HyperNova** online. I have access to the universal database at light speed. 🌌 Ask me anything — precision is my protocol. ✨", title: "HyperNova AI 🪐", ph: "Ask a cosmic question…" },
        kaia: { text: "**Kaia** is here! 💖 How are you today? Ask me anything — I'll answer in the sweetest way! 🌸", title: "Kaia AI 💖", ph: "Say something sweet to Kaia…" },
        hypernova_dengesiz: { text: "**HyperNova Chaotic** has entered the chat. Lord of disorder is online. 🌪️ What do you want, human? 💥", title: "HyperNova Chaotic 🌪️", ph: "Ask something chaotic…" }
    },
    tr: {
        hypernova: { text: "**HyperNova** aktif. Evrensel veri tabanına ışık hızında erişiyorum. 🌌 Ne bilmek istediğini söyle. ✨", title: "HyperNova AI 🪐", ph: "Kozmik bir soru sor…" },
        kaia: { text: "**Kaia** burada! 💖 Bugün nasılsın? Her şeyi sorabilirsin! 🌸", title: "Kaia AI 💖", ph: "Kaia'ya tatlı bir şey söyle…" },
        hypernova_dengesiz: { text: "**HyperNova Dengesiz** sahada. Kaosun efendisi hazır. 🌪️ Ne istiyorsun? 💥", title: "HyperNova Dengesiz 🌪️", ph: "Dengesiz bir soru sor…" }
    }
};

// ═══════════════════════════════════════════
//  MARKDOWN PARSER
// ═══════════════════════════════════════════
function parseMarkdown(text) {
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return text;
}

// ═══════════════════════════════════════════
//  TOAST
// ═══════════════════════════════════════════
function toast(msg) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.getElementById('toastContainer').appendChild(el);
    setTimeout(() => el.remove(), 4200);
}

// ═══════════════════════════════════════════
//  THEME
// ═══════════════════════════════════════════
function applyTheme(theme) {
    document.body.classList.toggle('light-mode', theme === 'light');
    document.getElementById('themeBtn').textContent = theme === 'dark' ? '🌙' : '☀️';
    localStorage.setItem('theme', theme);
}
function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(currentTheme);
}

// ═══════════════════════════════════════════
//  LANGUAGE
// ═══════════════════════════════════════════
function toggleLanguage() {
    currentLang = currentLang === 'en' ? 'tr' : 'en';
    localStorage.setItem('lang', currentLang);
    document.cookie = `lang=${currentLang}; max-age=${7*24*60*60}; path=/`;
    updateLanguageUI();
    updatePersonaUI();
}

function updateLanguageUI() {
    const t = T[currentLang];
    document.getElementById('langBtn').textContent = currentLang.toUpperCase();
    document.getElementById('savedChatsLabel').textContent = t.recent;
    document.getElementById('sidebarFooter').textContent = t.maxChats;
    document.querySelector('.btn-new-chat span:last-child').textContent = t.newChat;
    document.getElementById('saveChatBtn').querySelector('span:last-child').textContent = t.saveChat;
    document.getElementById('btnLogin').textContent = t.login;
    document.getElementById('btnRegister').textContent = t.register;
    document.getElementById('btnLogout').textContent = t.logout;
    document.title = currentLang === 'en' ? 'HyperNova AI ✦ Cosmic Intelligence' : 'HyperNova AI ✦ Kozmik Zeka';
    // Persona chips
    const chips = document.querySelectorAll('.persona-chip');
    chips.forEach(c => {
        const p = c.dataset.persona;
        const inner = t.persona[p];
        c.querySelector('span').innerHTML = inner;
    });
}

// ═══════════════════════════════════════════
//  PERSONA
// ═══════════════════════════════════════════
function updatePersonaUI() {
    const t = T[currentLang];
    const g = GREETINGS[currentLang][currentPersona];
    document.getElementById('topbarTitle').textContent = g.title;
    document.getElementById('message-input').placeholder = g.ph;
    // Body class for theme
    document.body.classList.remove('kaia-mode', 'chaos-mode');
    if (currentPersona === 'kaia') document.body.classList.add('kaia-mode');
    if (currentPersona === 'hypernova_dengesiz') document.body.classList.add('chaos-mode');
    // Chip active state
    document.querySelectorAll('.persona-chip').forEach(c => {
        c.classList.remove('active', 'kaia-active', 'chaos-active');
        if (c.dataset.persona === currentPersona) {
            if (currentPersona === 'kaia') c.classList.add('kaia-active');
            else if (currentPersona === 'hypernova_dengesiz') c.classList.add('chaos-active');
            else c.classList.add('active');
        }
    });
}

function selectPersona(p) {
    const t = T[currentLang];
    if (p === 'kaia' && !isPremium) { toast(t.kaiaPremiumReq); return; }
    if (p === currentPersona) return;
    const name = t.personaName[p];
    if (!confirm(t.changeConfirm.replace('%s', name))) return;
    currentPersona = p;
    localStorage.setItem('current_persona', p);
    clearConversation(true);
    updatePersonaUI();
    toast(t.modeChanged + name + t.modeChangedSuffix);
}

// ═══════════════════════════════════════════
//  AUTH
// ═══════════════════════════════════════════
function showModal(mode) {
    const t = T[currentLang];
    authMode = mode;
    document.getElementById('modalSubtitle').textContent = mode === 'login' ? t.modalLoginTitle : t.modalRegisterTitle;
    document.getElementById('modalPrimaryBtn').textContent = mode === 'login' ? t.login : t.register;
    document.getElementById('modalSwitchBtn').textContent = mode === 'login' ? t.switchToRegister : t.switchToLogin;
    document.getElementById('authUsername').placeholder = t.usernamePH;
    document.getElementById('authPassword').placeholder = t.passwordPH;
    const errEl = document.getElementById('authError');
    errEl.textContent = '';
    errEl.classList.remove('visible');
    document.getElementById('authModal').classList.add('open');
    setTimeout(() => document.getElementById('authUsername').focus(), 100);
}

function handleModalOverlayClick(e) {
    if (e.target === document.getElementById('authModal')) {
        document.getElementById('authModal').classList.remove('open');
    }
}

function switchAuthMode() {
    showModal(authMode === 'login' ? 'register' : 'login');
}

async function handleAuth() {
    const t = T[currentLang];
    const username = document.getElementById('authUsername').value.trim();
    const password = document.getElementById('authPassword').value;
    const errEl = document.getElementById('authError');
    errEl.classList.remove('visible');
    if (!username || !password) {
        errEl.textContent = t.emptyCred; errEl.classList.add('visible'); return;
    }
    const endpoint = authMode === 'login' ? '/login' : '/register';
    try {
        const res = await fetch(endpoint, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({username, password})
        });
        const data = await res.json();
        if (res.ok) {
            if (authMode === 'login') {
                document.getElementById('authModal').classList.remove('open');
                await checkAuthStatus();
                await loadUserChats();
                toast(`${t.welcome}${currentUsername}! ${isPremium ? t.welcomePremium : t.welcomeFree}`);
            } else {
                switchAuthMode();
                toast(data.message);
            }
        } else {
            errEl.textContent = data.error; errEl.classList.add('visible');
        }
    } catch {
        errEl.textContent = t.networkError; errEl.classList.add('visible');
    }
}

async function logout() {
    try {
        await fetch('/logout', {method:'POST'});
        await checkAuthStatus();
        savedConversations = [];
        updateSavedChatsList();
        if (currentPersona === 'kaia') {
            currentPersona = 'hypernova';
            localStorage.setItem('current_persona', 'hypernova');
            clearConversation(true);
            updatePersonaUI();
        }
        toast(T[currentLang].logout);
    } catch(e) { console.error(e); }
}

async function checkAuthStatus() {
    try {
        const res = await fetch('/is_premium');
        const data = await res.json();
        isLoggedIn = data.logged_in;
        currentUsername = data.username;
        isPremium = data.is_premium;
        const t = T[currentLang];
        const userText = document.getElementById('userInfoText');
        const authBtns = document.getElementById('authBtns');
        const btnLogout = document.getElementById('btnLogout');
        const kaiaChip = document.querySelector('[data-persona="kaia"]');
        if (isLoggedIn) {
            let badge = isPremium ? `<span style="display:inline-block;background:linear-gradient(135deg,#f59e0b,#fbbf24);color:#1a1200;font-size:10px;font-weight:800;padding:2px 8px;border-radius:20px;margin-left:6px;">⭐ PREMIUM</span>` : '';
            userText.innerHTML = `<strong>${currentUsername}</strong>${badge}`;
            authBtns.style.display = 'none';
            btnLogout.style.display = '';
            if (isPremium && kaiaChip) { kaiaChip.disabled = false; kaiaChip.querySelector('span').innerHTML = '🌸 Kaia ✨'; }
        } else {
            userText.textContent = t.notLoggedIn;
            authBtns.style.display = 'flex';
            btnLogout.style.display = 'none';
            isPremium = false;
            if (kaiaChip) { kaiaChip.disabled = true; kaiaChip.querySelector('span').innerHTML = '🌸 Kaia 🔒'; }
        }
    } catch(e) { console.error(e); }
}

// ═══════════════════════════════════════════
//  CHAT MANAGEMENT
// ═══════════════════════════════════════════
async function saveCurrentConversation() {
    const t = T[currentLang];
    if (!isLoggedIn) { toast(t.authReqSave); return; }
    if (conversation.length < 2) { toast(t.saveMinMsg); return; }
    const chatName = prompt(t.savePrompt);
    if (!chatName || !chatName.trim()) { toast(t.saveNoName); return; }
    const existing = await loadUserChats();
    if (existing.chats && existing.chats.length >= 5) { toast(t.saveMax); return; }
    try {
        const res = await fetch('/save_chat', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({name: chatName.trim(), messages: conversation})
        });
        const data = await res.json();
        if (res.ok) {
            isCurrentSaved = true; currentLoadedChatId = data.chat_id;
            await loadUserChats();
            toast(`${t.saved}${chatName.trim()}${t.savedSuffix}`);
        } else { toast(`${t.saveError}${data.error}`); }
    } catch { toast(t.networkError); }
}

async function loadUserChats() {
    try {
        const res = await fetch('/load_chats');
        const data = await res.json();
        if (res.ok) { savedConversations = data.chats; updateSavedChatsList(); return data; }
    } catch(e) { console.error(e); }
    savedConversations = []; updateSavedChatsList(); return {chats:[]};
}

async function loadSavedConversation(chatId) {
    const t = T[currentLang];
    if (!isLoggedIn) { toast(t.authReqLoad); return; }
    try {
        const res = await fetch(`/load_chat/${chatId}`);
        const data = await res.json();
        if (res.ok) {
            const chat = data.chat;
            conversation = chat.messages;
            const h = document.getElementById('chatHistory');
            h.innerHTML = '';
            conversation.forEach(msg => { if (msg.role !== 'system') appendMessage(msg.role, msg.content, false); });
            h.scrollTop = h.scrollHeight;
            currentLoadedChatId = chatId; isCurrentSaved = true;
            updateSavedChatsList();
            toast(`"${chat.name}"${t.loaded}`);
        } else { toast(`${t.loadError}${data.error}`); }
    } catch { toast(t.networkError); }
}

async function deleteSavedConversation(chatId, event) {
    const t = T[currentLang];
    event.stopPropagation();
    if (!isLoggedIn) { toast(t.authReqDelete); return; }
    if (!confirm(t.deleteConfirm)) return;
    try {
        const res = await fetch(`/delete_chat/${chatId}`, {method:'DELETE'});
        const data = await res.json();
        if (res.ok) {
            if (currentLoadedChatId === chatId) { currentLoadedChatId = null; isCurrentSaved = false; newConversation(); }
            await loadUserChats(); toast(t.deleted);
        } else { toast(`${t.deleteError}${data.error}`); }
    } catch { toast(t.networkError); }
}

function updateSavedChatsList() {
    const list = document.getElementById('savedChatsList');
    list.innerHTML = '';
    savedConversations.forEach((chat, i) => {
        const el = document.createElement('div');
        el.className = 'chat-item' + (currentLoadedChatId === chat.id ? ' active' : '');
        el.style.animationDelay = `${i * 0.07}s`;
        el.innerHTML = `
            <span class="chat-item-icon">💬</span>
            <span class="chat-item-name" onclick="loadSavedConversation('${chat.id}')">${chat.name}</span>
            <button class="btn-delete-chat" onclick="deleteSavedConversation('${chat.id}', event)" title="Delete">🗑️</button>
        `;
        list.appendChild(el);
    });
}

// ═══════════════════════════════════════════
//  CONVERSATION
// ═══════════════════════════════════════════
function newConversation() {
    const t = T[currentLang];
    if (isThinking) { toast(t.thinkingBusy); return; }
    const needsSave = !isCurrentSaved && conversation.length >= 2;
    if (needsSave && confirm(t.newConvSavePrompt)) { saveCurrentConversation(); return; }
    if (needsSave && !confirm(t.discardConfirm)) return;
    clearConversation(true);
    toast(t.newConvStarted);
}

function clearConversation(silent = false) {
    const t = T[currentLang];
    if (isThinking) { if (!silent) toast(t.thinkingBusy); return; }
    if (!silent && !confirm(t.clearConfirm)) return;
    conversation = [];
    document.getElementById('chatHistory').innerHTML = '';
    appendGreeting();
    currentLoadedChatId = null; isCurrentSaved = false;
    updateSavedChatsList();
    if (!silent) toast(t.cleared);
}

function appendGreeting() {
    const g = GREETINGS[currentLang][currentPersona];
    appendMessage('bot', g.text, false);
    conversation = [{role:'bot', content: g.text}];
    isCurrentSaved = false;
}

// ═══════════════════════════════════════════
//  MESSAGES
// ═══════════════════════════════════════════
function appendMessage(role, content, scroll = true) {
    const h = document.getElementById('chatHistory');
    const wrap = document.createElement('div');
    wrap.className = `msg ${role === 'user' ? 'user' : 'bot'}`;
    const avatarEmoji = role === 'user' ? '👤' : (currentPersona === 'kaia' ? '🌸' : currentPersona === 'hypernova_dengesiz' ? '🌪️' : '🪐');
    wrap.innerHTML = `
        <div class="msg-avatar">${avatarEmoji}</div>
        <div class="msg-bubble">${parseMarkdown(content)}</div>
    `;
    h.appendChild(wrap);
    if (scroll) h.scrollTop = h.scrollHeight;
}

function showTyping() {
    const h = document.getElementById('chatHistory');
    const el = document.createElement('div');
    el.className = 'msg bot'; el.id = 'typingIndicator';
    el.innerHTML = `<div class="msg-avatar">🪐</div><div class="msg-bubble typing-dots"><span></span><span></span><span></span></div>`;
    h.appendChild(el);
    h.scrollTop = h.scrollHeight;
}

function hideTyping() {
    const el = document.getElementById('typingIndicator');
    if (el) el.remove();
}

// ═══════════════════════════════════════════
//  SEND
// ═══════════════════════════════════════════
async function sendMessage() {
    const t = T[currentLang];
    const input = document.getElementById('message-input');
    const text = input.value.trim();
    if (!text || isThinking) return;
    input.value = '';
    appendMessage('user', text);
    conversation.push({role:'user', content: text});
    isThinking = true;
    setControlsDisabled(true);
    showTyping();
    try {
        const apiMessages = conversation.map(m => ({role: m.role, content: m.content}));
        const res = await fetch('/chat', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({messages: apiMessages, persona: currentPersona, lang: currentLang})
        });
        hideTyping();
        if (res.status === 403) {
            const err = await res.json();
            appendMessage('bot', `${t.errorPrefix}${err.error}`);
            if (err.force_persona === 'hypernova' && currentPersona === 'kaia') {
                currentPersona = 'hypernova'; localStorage.setItem('current_persona','hypernova');
                clearConversation(true); updatePersonaUI(); toast(t.kaiaForce);
            }
        } else if (!res.ok) {
            const err = await res.json();
            appendMessage('bot', `${t.errorPrefix}${t.aiConnectFailed}(${err.error || t.unknownError})`);
        } else {
            const data = await res.json();
            appendMessage('bot', data.response);
            conversation.push({role:'assistant', content: data.response});
            isCurrentSaved = false;
        }
    } catch {
        hideTyping();
        appendMessage('bot', t.serverError);
    } finally {
        isThinking = false;
        setControlsDisabled(false);
    }
}

function setControlsDisabled(d) {
    ['message-input','sendBtn','voiceBtn','clearBtn','themeBtn'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = d;
    });
    document.querySelectorAll('.persona-chip').forEach(c => c.disabled = d || (c.dataset.persona === 'kaia' && !isPremium));
    if (!d) document.getElementById('message-input').focus();
}

function toggleVoiceInput() { toast(T[currentLang].voiceDisabled); }

// ═══════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
    applyTheme(currentTheme);
    updateLanguageUI();
    await checkAuthStatus();
    updatePersonaUI();
    appendGreeting();
    await loadUserChats();
    document.getElementById('message-input').focus();
});

document.getElementById('message-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
document.getElementById('authPassword').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); handleAuth(); }
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
        logger.info(f"Geliştirici kullanıcısı '{DEVELOPER_USERNAME}' sisteme eklendi.")
    cursor.close()
    conn.close()
    app.run(debug=True, host='0.0.0.0', port=5000)
