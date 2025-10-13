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
    logger.info(f"DB Bağlantı Detayları: Host={url.hostname}, Port={url.port}, User={url.username}, DB={url.path[1:]}")  # Debug log
    
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    conn.cursor_factory = RealDictCursor  # Dict-like rows için
    return conn

def init_db():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable'ı ayarlanmadı!")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Kullanıcılar tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            premium_until TIMESTAMP NOT NULL
        )
    ''')
    
    # Sohbetler tablosu (Kullanıcıya bağlı)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            messages TEXT NOT NULL,  -- JSON string
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Supabase veritabanı başlatıldı.")

# Başlangıçta DB'yi başlat
init_db()

# --- SESSION MAP (In-Memory - Kısa Süreli) ---
SESSION_MAP: Dict[str, str] = {}  # session_id: username

# Geliştirici kullanıcı adı (Admin paneline erişim için)
DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD = "TheLastGalaxy*"  # Gerçekte hashlenmeli!

# API Hata Türleri (tenacity için)
class APIRequestError(Exception):
    """API isteği sırasında yaşanan hatalar için özel istisna."""
    pass

# --- Flask Uygulaması ve Eklentilerin Başlatılması ---
app = Flask(__name__)
CORS(app)

# Flask-Limiter: IP adresine göre dakikada 10 istek limiti uygular
limiter = Limiter(
    app=app,
    key_prefix="hypernova_chat",
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

# --- YARDIMCI FONKSİYONLAR (DB İşlemleri) ---

def get_user_id(username: str) -> Optional[int]:
    """Kullanıcı ID'sini döndürür."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['id'] if row else None

def get_current_user() -> Optional[str]:
    """Cookie'den session_id'yi alır ve kullanıcı adını döndürür."""
    session_id = request.cookies.get('session_id')
    return SESSION_MAP.get(session_id)

def is_user_premium(username: str) -> bool:
    """Kullanıcının premium üyeliğinin aktif olup olmadığını kontrol eder."""
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
    """Premium bitiş tarihini döndürür."""
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
    """Yeni kullanıcı oluşturur."""
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
    """Kullanıcıyı doğrular."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row and row['password'] == password

def check_admin_auth(username: str, password: str) -> bool:
    """Geliştirici (Admin) girişi için kontrol."""
    return username == DEVELOPER_USERNAME and password == DEVELOPER_PASSWORD

def grant_premium(username: str, days: int = 30):
    """Kullanıcıya premium verir."""
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
    """Sohbeti kaydeder ve ID döndürür."""
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
    """Kullanıcının sohbetlerini döndürür (20 gün kuralı ile)."""
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
    """Sohbeti yükler."""
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
    """Sohbeti siler."""
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
    """UI çevirisi alır."""
    return UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['en']).get(key, key)

def get_system_prompts(lang: str):
    """Dil'e göre system prompts döndürür."""
    return SYSTEM_PROMPTS_EN if lang == 'en' else SYSTEM_PROMPTS_TR

# --- Asenkron API Çağrısı Fonksiyonu (Retry Mekanizması ile) ---

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
    """Asenkron API çağrısı yapar ve hata durumunda tekrar dener."""

    # Seçilen persona'ya göre system prompt'u ayarla
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

# --- Flask Rotaları (Authentication/Chat/Admin) ---

@app.route('/is_premium', methods=['GET'])
def is_premium_endpoint():
    """Kullanıcının premium durumunu kontrol eden API."""
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
        # Premium olmayan kullanıcılar için bile chate izin verelim, 
        # sadece Kaia modunu kısıtlayalım (HyperNova ücretsiz kalsın)
        pass 

    try:
        data = request.get_json()
        messages = data.get('messages', [])
        persona = data.get('persona', DEFAULT_PERSONA)

        messages = [
            {**msg, 'role': 'assistant' if msg['role'] == 'bot' else msg['role']}
            for msg in messages
        ]

        # --- PREMIUM KONTROLÜ (KAIA MODU İÇİN) ---
        if persona == "kaia":
            if not username or not is_user_premium(username):
                # Premium değilse veya giriş yapmamışsa Kaia modunu engelle
                return jsonify({
                    "error": get_ui_translation(lang, 'kaia_premium'),
                    "force_persona": DEFAULT_PERSONA # Frontend'e HyperNova'ya geçmesini söyle
                }), 403
            logger.info(f"Premium kullanıcı '{username}' Kaia modunu kullanıyor.")

        # API çağrısı
        bot_response = await async_chat_completion(messages, MODEL_DEFAULT, persona, lang)

        # Yanıtı döndür
        return jsonify({"response": bleach.clean(bot_response)}), 200

    except APIRequestError as e:
        logger.error(f"API İstek Hatası: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.error(f"Sunucu Hatası: {e}")
        return jsonify({"error": "Dahili Sunucu Hatası: " + str(e)}), 500

# --- SOHBET YÖNETİM API'LERİ (YENİ) ---

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
    
    # Maksimum 5 sohbet kontrolü
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

# --- Kullanıcı Yönetim Rotaları ---

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
        # Başarılı giriş: Yeni session ID oluştur
        session_id = str(uuid.uuid4())
        SESSION_MAP[session_id] = username

        # Premium durumunu kontrol et
        is_premium = is_user_premium(username)

        logger.info(f"Kullanıcı giriş yaptı: {username} (Premium: {is_premium})")

        # Cookie ile session ID'yi ayarla
        response = make_response(jsonify({
            "message": get_ui_translation(lang, 'login_success'), 
            "username": username,
            "is_premium": is_premium
        }))
        # Secure, HttpOnly ve SameSite=Lax (ya da Strict) gerçek bir uygulamada ayarlanmalı
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
    response.set_cookie('session_id', '', expires=0) # Cookie'yi sil
    return response

# --- GELİŞTİRİCİ / ADMIN PANEL ROTASI (GÜNCELLENDİ: DB Kullanımı) ---

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    # Admin girişini kontrol et (Cookie kullanmadan, basit bir form ile)
    is_authenticated = False

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'login':
            admin_user = request.form.get('admin_username')
            admin_pass = request.form.get('admin_password')
            if check_admin_auth(admin_user, admin_pass):
                # Başarılı giriş, bir session cookie'si oluşturabiliriz, 
                # ancak demo için sadece bu isteğin devamında yetki verelim.
                is_authenticated = True
                return redirect(url_for('admin_panel', auth='success')) # URL'e basit bir flag ekleyelim
            else:
                return admin_login_template("Geçersiz Yönetici Kimlik Bilgisi."), 401

        elif form_type == 'premium_grant':
            # Bu işlem için admin'in giriş yapması gerekir, ancak demo'da 
            # yukarıdaki form girişini atlayıp direkt işlem yapmaya çalışacağız
            # VEYA basit bir kontrol daha ekleriz:

            # Geliştirici kimlik bilgileri tekrar kontrol edilir
            admin_user = request.form.get('auth_username')
            admin_pass = request.form.get('auth_password')

            if not check_admin_auth(admin_user, admin_pass):
                return admin_login_template("Yetkisiz İşlem Denemesi. Lütfen Yönetici olarak giriş yapın."), 403

            is_authenticated = True

            target_username = request.form.get('target_username')

            if get_user_id(target_username) is None:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** bulunamadı."), 404

            # Premium Süresini Ayarla (Şimdiden 30 gün sonrası)
            if grant_premium(target_username):
                logger.info(f"Admin: {target_username} kullanıcısının premiumluğu uzatıldı.")

                # Başarı mesajı ile admin panelini yeniden yükle
                message = f"Başarılı! **{target_username}** kullanıcısının premium üyeliği **{ (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')}** tarihine kadar aktifleştirildi (30 gün)."
                return admin_panel_template(message, is_authenticated)
            else:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** premium verilemedi."), 500


    # GET isteği veya ilk yükleme
    if request.args.get('auth') == 'success' or request.args.get('auth_user') == DEVELOPER_USERNAME:
        is_authenticated = True # Basit demo yetkilendirmesi

    if is_authenticated:
        return admin_panel_template("", is_authenticated)
    else:
        return admin_login_template()

def admin_login_template(error_message: str = ""):
    """Admin Giriş Formu HTML'i."""
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
    """Admin Paneli HTML'i (Premium Aktifleştirme Formu ve Kullanıcı Listesi)."""

    # Eğer yetkilendirme yoksa, giriş sayfasına yönlendir
    if not is_authenticated:
        return redirect(url_for('admin_panel'))

    # Kullanıcı verilerini premium durumuna göre hazırla
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

    # Admin panelinin HTML'i
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
            
            /* Form Stili */
            form {{ background: #4b5563; padding: 20px; border-radius: 8px; margin-bottom: 30px; }}
            label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #d1d5db; }}
            input[type="text"] {{ width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #6b7280; border-radius: 6px; box-sizing: border-box; background: #374151; color: #f9fafb; }}
            button {{ padding: 10px 20px; background-color: #8b5cf6; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }}
            button:hover {{ background-color: #a78bfa; }}
            
            /* Tablo Stili */
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
    """Ana sayfa: Frontend arayüzünü döndürür."""
    # HTML, CSS ve JS kodları aşağıdadır... (Frontend güncellendi: API çağrıları ile sohbet yönetimi)
    # *** DEĞİŞİKLİK: JS regex'inde backslash'leri escape et (Python string'i için) ***
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NovaForge AI ✦ Quantum Nexus</title>
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            /* --- Quantum Theme: Neon Glow, Glassmorphism & Particle Animations --- */
            :root {
                /* Core Quantum Palette */
                --quantum-bg: linear-gradient(135deg, #0c0c1a 0%, #1a0a2e 50%, #0f0f23 100%);
                --glass-bg: rgba(255, 255, 255, 0.05);
                --glass-border: rgba(255, 255, 255, 0.1);
                --neon-primary: #00ffff; /* Cyan Neon */
                --neon-secondary: #ff00ff; /* Magenta Neon */
                --neon-accent: #ffff00; /* Yellow Glow */
                --text-primary: #e0e7ff;
                --text-secondary: #a1a1aa;
                --user-bubble: rgba(0, 255, 255, 0.2);
                --bot-bubble: rgba(255, 0, 255, 0.1);
                --shadow-neon: 0 0 20px rgba(0, 255, 255, 0.5);
                --shadow-magenta: 0 0 20px rgba(255, 0, 255, 0.5);

                /* Kaia Variant: Soft Pastel Neon */
                --kaia-neon: #ff69b4;
                --kaia-bg: linear-gradient(135deg, #ff9a9e 0%, #fecfef 50%, #fecfef 100%);
                --kaia-glass: rgba(255, 182, 193, 0.1);
            }

            @media (prefers-color-scheme: dark) {
                :root {
                    --quantum-bg: linear-gradient(135deg, #000000 0%, #0a0a0a 50%, #1a1a2e 100%);
                    --text-primary: #f0f0ff;
                }
            }

            body.light-quantum {
                --quantum-bg: linear-gradient(135deg, #f0f8ff 0%, #e6f3ff 50%, #f8f9ff 100%);
                --glass-bg: rgba(0, 0, 0, 0.05);
                --neon-primary: #0066cc;
                --text-primary: #1a1a2a;
            }

            /* Kaia Overrides */
            body.kaia-theme {
                --quantum-bg: var(--kaia-bg);
                --neon-primary: var(--kaia-neon);
                --glass-bg: var(--kaia-glass);
                --text-primary: #4a0e32;
                --user-bubble: rgba(255, 105, 180, 0.3);
                --bot-bubble: rgba(255, 182, 193, 0.2);
            }

            /* Global Styles */
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            body {
                font-family: 'Poppins', sans-serif;
                background: var(--quantum-bg);
                color: var(--text-primary);
                overflow: hidden;
                transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1);
            }

            /* Animated Background Particles */
            .particles {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: -1;
            }

            .particle {
                position: absolute;
                width: 2px;
                height: 2px;
                background: var(--neon-primary);
                border-radius: 50%;
                animation: float 20s infinite linear;
            }

            @keyframes float {
                0% { transform: translateY(100vh) rotate(0deg); opacity: 0; }
                10% { opacity: 1; }
                90% { opacity: 1; }
                100% { transform: translateY(-100px) rotate(360deg); opacity: 0; }
            }

            /* Main Layout: Full-Screen with Floating Elements */
            .nexus-container {
                height: 100vh;
                display: grid;
                grid-template-rows: auto 1fr auto;
                gap: 0;
                position: relative;
            }

            /* Top Nexus Bar: Controls & Auth */
            .nexus-bar {
                background: var(--glass-bg);
                backdrop-filter: blur(20px);
                border-bottom: 1px solid var(--glass-border);
                padding: 12px 24px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: var(--shadow-neon);
                animation: barGlow 3s ease-in-out infinite alternate;
            }

            @keyframes barGlow {
                0% { box-shadow: var(--shadow-neon); }
                100% { box-shadow: 0 0 30px var(--neon-secondary); }
            }

            .nexus-title {
                font-size: 28px;
                font-weight: 800;
                background: linear-gradient(45deg, var(--neon-primary), var(--neon-secondary));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                animation: titlePulse 2s ease-in-out infinite;
            }

            @keyframes titlePulse {
                0%, 100% { filter: hue-rotate(0deg) brightness(1); }
                50% { filter: hue-rotate(180deg) brightness(1.2); }
            }

            .controls-grid {
                display: grid;
                grid-template-columns: repeat(4, auto);
                gap: 12px;
                align-items: center;
            }

            .control-btn {
                background: var(--glass-bg);
                border: 1px solid var(--glass-border);
                border-radius: 50%;
                width: 44px;
                height: 44px;
                cursor: pointer;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 18px;
                color: var(--neon-primary);
            }

            .control-btn:hover {
                transform: scale(1.1) rotate(5deg);
                box-shadow: var(--shadow-neon);
                background: rgba(0, 255, 255, 0.1);
            }

            #persona-select {
                background: var(--glass-bg);
                border: 1px solid var(--glass-border);
                border-radius: 20px;
                padding: 8px 16px;
                color: var(--text-primary);
                font-weight: 500;
                cursor: pointer;
                min-width: 180px;
                transition: all 0.3s;
            }

            #persona-select option {
                background: var(--quantum-bg);
                color: var(--text-primary);
            }

            #auth-status {
                display: flex;
                gap: 8px;
                align-items: center;
                background: var(--glass-bg);
                padding: 6px 12px;
                border-radius: 20px;
                font-weight: 500;
                border: 1px solid var(--glass-border);
            }

            .auth-btn {
                background: var(--neon-secondary);
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 15px;
                cursor: pointer;
                font-weight: 500;
                transition: all 0.3s;
            }

            .auth-btn:hover {
                box-shadow: var(--shadow-magenta);
                transform: translateY(-2px);
            }

            /* Chat Nexus: Floating Orb Layout */
            .chat-nexus {
                position: relative;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow: hidden;
            }

            .chat-orb {
                width: 90%;
                max-width: 700px;
                height: 80%;
                background: var(--glass-bg);
                backdrop-filter: blur(30px);
                border-radius: 50%;
                border: 1px solid var(--glass-border);
                display: flex;
                flex-direction: column;
                position: relative;
                overflow: hidden;
                box-shadow: inset 0 0 50px rgba(0, 255, 255, 0.1), var(--shadow-neon);
                animation: orbFloat 6s ease-in-out infinite;
            }

            @keyframes orbFloat {
                0%, 100% { transform: translateY(0px) rotate(0deg); }
                50% { transform: translateY(-10px) rotate(1deg); }
            }

            .orb-header {
                padding: 20px;
                text-align: center;
                border-bottom: 1px solid var(--glass-border);
                position: relative;
            }

            .orb-title {
                font-size: 24px;
                font-weight: 700;
                color: var(--neon-primary);
                text-shadow: 0 0 10px var(--neon-primary);
            }

            #chat-history {
                flex: 1;
                padding: 20px;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 15px;
                scroll-behavior: smooth;
            }

            #chat-history::-webkit-scrollbar {
                width: 6px;
            }

            #chat-history::-webkit-scrollbar-thumb {
                background: var(--neon-primary);
                border-radius: 3px;
                opacity: 0.5;
            }

            .message {
                max-width: 80%;
                padding: 16px 20px;
                border-radius: 25px;
                animation: messageSlide 0.5s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: var(--shadow-neon);
                position: relative;
            }

            @keyframes messageSlide {
                from {
                    opacity: 0;
                    transform: translateX(50px) scale(0.9);
                }
                to {
                    opacity: 1;
                    transform: translateX(0) scale(1);
                }
            }

            .user {
                background: var(--user-bubble);
                border: 1px solid var(--neon-primary);
                align-self: flex-end;
                margin-left: auto;
                color: var(--neon-primary);
            }

            .bot {
                background: var(--bot-bubble);
                border: 1px solid var(--neon-secondary);
                align-self: flex-start;
                color: var(--text-primary);
            }

            /* Input Nexus: Bottom Floating Bar */
            .input-nexus {
                background: var(--glass-bg);
                backdrop-filter: blur(20px);
                border-top: 1px solid var(--glass-border);
                padding: 16px 24px;
                display: flex;
                gap: 12px;
                align-items: center;
                box-shadow: var(--shadow-neon);
            }

            #message-input {
                flex: 1;
                padding: 14px 20px;
                background: var(--glass-bg);
                border: 1px solid var(--glass-border);
                border-radius: 25px;
                color: var(--text-primary);
                font-size: 16px;
                outline: none;
                transition: all 0.3s;
            }

            #message-input:focus {
                border-color: var(--neon-primary);
                box-shadow: var(--shadow-neon);
            }

            .send-btn {
                background: linear-gradient(45deg, var(--neon-primary), var(--neon-secondary));
                color: white;
                border: none;
                padding: 14px 24px;
                border-radius: 25px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s;
                box-shadow: var(--shadow-neon);
            }

            .send-btn:hover {
                transform: scale(1.05);
                box-shadow: 0 0 25px var(--neon-primary);
            }

            /* Modal: Quantum Portal */
            .modal {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.8);
                backdrop-filter: blur(10px);
                display: none;
                justify-content: center;
                align-items: center;
                z-index: 1000;
                animation: portalOpen 0.4s ease-out;
            }

            @keyframes portalOpen {
                from { opacity: 0; }
                to { opacity: 1; }
            }

            .modal-content {
                background: var(--glass-bg);
                padding: 40px;
                border-radius: 30px;
                border: 1px solid var(--glass-border);
                width: 90%;
                max-width: 400px;
                text-align: center;
                box-shadow: var(--shadow-neon);
                animation: modalFloat 0.6s ease-out;
            }

            @keyframes modalFloat {
                0% { transform: scale(0.8) translateY(50px); opacity: 0; }
                100% { transform: scale(1) translateY(0); opacity: 1; }
            }

            .modal-content input {
                width: 100%;
                padding: 14px;
                margin: 10px 0;
                background: var(--glass-bg);
                border: 1px solid var(--glass-border);
                border-radius: 15px;
                color: var(--text-primary);
                font-size: 16px;
            }

            .modal-btn {
                width: 100%;
                padding: 12px;
                margin: 8px 0;
                border: none;
                border-radius: 15px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s;
            }

            .login-btn { background: var(--neon-primary); color: white; }
            .register-btn { background: var(--neon-secondary); color: white; }

            .modal-btn:hover {
                transform: translateY(-3px);
                box-shadow: var(--shadow-neon);
            }

            /* Typing Indicator: Wave Effect */
            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 16px 20px;
                border-radius: 25px;
                background: var(--bot-bubble);
                border: 1px solid var(--neon-secondary);
                align-self: flex-start;
                animation: wave 1.5s infinite;
            }

            @keyframes wave {
                0%, 100% { transform: translateX(0); }
                50% { transform: translateX(10px); }
            }

            .wave-dot {
                width: 8px;
                height: 8px;
                background: var(--neon-primary);
                border-radius: 50%;
                animation: dotWave 1.5s infinite;
            }

            .wave-dot:nth-child(2) { animation-delay: 0.2s; }
            .wave-dot:nth-child(3) { animation-delay: 0.4s; }

            @keyframes dotWave {
                0%, 60%, 100% { transform: scale(1); opacity: 0.5; }
                30% { transform: scale(1.5); opacity: 1; }
            }

            /* Responsive: Mobile Orb Collapse */
            @media (max-width: 768px) {
                .chat-orb {
                    width: 100%;
                    height: 70%;
                    border-radius: 20px;
                }

                .controls-grid {
                    grid-template-columns: repeat(2, auto);
                }

                .nexus-bar {
                    padding: 12px;
                    flex-wrap: wrap;
                }

                .nexus-title {
                    font-size: 22px;
                }
            }

            /* Saved Chats: Side Drawer (Toggle Hidden) */
            .drawer {
                position: fixed;
                top: 0;
                right: -300px;
                width: 300px;
                height: 100vh;
                background: var(--glass-bg);
                backdrop-filter: blur(20px);
                border-left: 1px solid var(--glass-border);
                transition: right 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                z-index: 999;
                padding: 20px;
                overflow-y: auto;
                box-shadow: -5px 0 30px rgba(0, 0, 0, 0.3);
            }

            .drawer.open {
                right: 0;
            }

            .saved-item {
                background: rgba(255, 255, 255, 0.05);
                padding: 12px;
                margin: 8px 0;
                border-radius: 15px;
                cursor: pointer;
                transition: all 0.3s;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .saved-item:hover {
                background: rgba(0, 255, 255, 0.1);
                transform: translateX(-5px);
                box-shadow: var(--shadow-neon);
            }

            .delete-saved {
                background: none;
                border: none;
                color: #ff4444;
                font-size: 18px;
                cursor: pointer;
                opacity: 0.7;
                transition: opacity 0.3s;
            }

            .delete-saved:hover {
                opacity: 1;
                transform: scale(1.2);
            }

            .drawer-toggle {
                position: fixed;
                top: 50%;
                right: 10px;
                transform: translateY(-50%);
                background: var(--neon-primary);
                color: white;
                border: none;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                cursor: pointer;
                z-index: 1000;
                box-shadow: var(--shadow-neon);
                transition: all 0.3s;
            }

            .drawer-toggle:hover {
                transform: translateY(-50%) scale(1.1);
            }
        </style>
    </head>
    <body>
        <!-- Animated Particles Background -->
        <div class="particles" id="particles"></div>

        <!-- Drawer for Saved Chats -->
        <button class="drawer-toggle" onclick="toggleDrawer()">📁</button>
        <div class="drawer" id="drawer">
            <h3 style="margin-bottom: 20px; color: var(--neon-primary);">Quantum Vault</h3>
            <button onclick="newConversation()" style="width: 100%; padding: 12px; background: var(--neon-secondary); color: white; border: none; border-radius: 15px; margin-bottom: 15px; cursor: pointer;">New Quantum Thread</button>
            <div id="saved-chats-list"></div>
            <p style="text-align: center; opacity: 0.6; font-size: 12px; margin-top: 20px;">Max 5 Threads</p>
        </div>

        <!-- Auth Modal -->
        <div id="authModal" class="modal" onclick="closeModal(event)">
            <div class="modal-content">
                <h3 id="modalTitle">Quantum Access</h3>
                <p id="auth-message" style="color: #ff4444; display: none; margin-bottom: 15px;"></p>
                <input type="text" id="authUsername" placeholder="Nexus ID">
                <input type="password" id="authPassword" placeholder="Quantum Key">
                <button class="modal-btn login-btn" onclick="handleAuth()">Enter Nexus</button>
                <button class="modal-btn register-btn" onclick="switchAuthMode()" style="background: var(--neon-secondary);">Forge New ID</button>
            </div>
        </div>

        <div class="nexus-container">
            <!-- Top Bar -->
            <div class="nexus-bar">
                <div class="nexus-title">NovaForge AI ⚛️</div>
                <div id="auth-status">
                    <span id="user-info">Quantum Guest</span>
                    <div id="auth-buttons">
                        <button class="auth-btn" onclick="showModal('login')">Access</button>
                        <button class="auth-btn" onclick="showModal('register')">Forge</button>
                        <button id="logout-button" class="auth-btn" style="display: none;" onclick="logout()">Eject</button>
                    </div>
                </div>
                <div class="controls-grid">
                    <button class="control-btn" id="clear-button" onclick="clearConversation()" title="Purge Thread">🧹</button>
                    <button class="control-btn" id="theme-toggle" onclick="toggleTheme()" title="Shift Spectrum">⚡</button>
                    <button class="control-btn" id="lang-toggle" onclick="toggleLanguage()" title="Echo Language">🌐</button>
                    <button class="control-btn" id="voice-button" onclick="toggleVoiceInput()" title="Vocal Pulse">🎤</button>
                    <select id="persona-select" onchange="changePersona()">
                        <option value="hypernova">Nova Core ⚛️</option>
                        <option value="kaia" disabled>Kai Pulse 💫 (Premium)</option>
                        <option value="hypernova_dengesiz">Chaos Flux 🌪️</option>
                    </select>
                </div>
            </div>

            <!-- Chat Orb -->
            <div class="chat-nexus">
                <div class="chat-orb">
                    <div class="orb-header">
                        <div class="orb-title" id="orb-title">Initiate Quantum Dialogue</div>
                    </div>
                    <div id="chat-history"></div>
                    <div class="input-nexus">
                        <input type="text" id="message-input" placeholder="Transmit quantum query..." onkeypress="if(event.key==='Enter') sendMessage()">
                        <button class="send-btn" id="send-button" onclick="sendMessage()">Transmit</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // ... (Keep the same JS logic, but update selectors and texts for new UI)
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
            const drawer = document.getElementById('drawer');
            const savedChatsList = document.getElementById('saved-chats-list');

            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let authMode = 'login';
            let currentLang = localStorage.getItem('lang') || 'en';
            let currentPersona = localStorage.getItem('current_persona') || 'hypernova';
            let currentTheme = localStorage.getItem('theme') || 'dark';

            // Updated Translations for New UI
            const TRANSLATIONS = {
                en: {
                    // ... (same as before, but add new keys if needed)
                    quantumGuest: 'Quantum Guest',
                    access: 'Access',
                    forge: 'Forge',
                    eject: 'Eject',
                    initiate: 'Initiate Quantum Dialogue',
                    transmit: 'Transmit',
                    // etc.
                },
                tr: {
                    // ... (same)
                }
            };

            // Updated Greetings for New Theme
            const GREETINGS = {
                en: {
                    hypernova: {
                        text: "**NovaForge** activated. Quantum entanglement established. ⚛️ Transmit your query for instantaneous response across the multiverse.",
                        title: "NovaForge AI ⚛️",
                        placeholder: "Transmit quantum query..."
                    },
                    // ... (adapt others)
                },
                // ... (tr too)
            };

            // Particle Generator
            function createParticles() {
                const particlesContainer = document.getElementById('particles');
                for (let i = 0; i < 50; i++) {
                    const particle = document.createElement('div');
                    particle.className = 'particle';
                    particle.style.left = Math.random() * 100 + '%';
                    particle.style.animationDuration = (Math.random() * 20 + 10) + 's';
                    particle.style.animationDelay = Math.random() * 5 + 's';
                    particlesContainer.appendChild(particle);
                }
            }

            // Drawer Toggle
            function toggleDrawer() {
                drawer.classList.toggle('open');
            }

            // Update other functions similarly, adapting selectors like .saved-chat to .saved-item, etc.
            // For example, updateSavedChatsList():
            function updateSavedChatsList() {
                savedChatsList.innerHTML = '';
                savedConversations.forEach((chat, index) => {
                    const chatElement = document.createElement('div');
                    chatElement.className = 'saved-item';
                    chatElement.style.animationDelay = `${index * 0.1}s`;
                    if (currentLoadedChatId === chat.id) {
                        chatElement.style.background = 'rgba(0, 255, 255, 0.2)';
                    }
                    chatElement.innerHTML = `
                        <span onclick="loadSavedConversation('${chat.id}')">${chat.name}</span>
                        <button class="delete-saved" onclick="deleteSavedConversation('${chat.id}', event)">✕</button>
                    `;
                    savedChatsList.appendChild(chatElement);
                });
            }

            // Apply Theme (Updated)
            function applyTheme(theme) {
                document.body.className = theme === 'light' ? 'light-quantum' : '';
                if (currentPersona === 'kaia') {
                    document.body.classList.add('kaia-theme');
                }
                themeToggle.innerHTML = theme === 'dark' ? '🌑' : '☀️';
                localStorage.setItem('theme', theme);
            }

            // ... (Rest of JS remains largely the same, with minor selector updates for new classes)

            // Init
            document.addEventListener('DOMContentLoaded', async () => {
                createParticles();
                await loadUserChats();
                await checkAuthStatus();
                updateLanguage();
                updateUIForPersona();
                displayInitialGreeting();
            });

            // ... (all other functions as before)
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


if __name__ == '__main__':
    # Geliştirici kullanıcısını önceden kaydet (DB'ye)
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
