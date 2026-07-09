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
MODEL_DEFAULT = "deepseek/deepseek-v4-flash"
UI_TRANSLATIONS = {
    'en': {
        'register_success': 'Registration successful. You can now log in.',
        'user_exists': 'This username is already taken.',
        'login_success': 'Login successful.',
        'invalid_creds': 'Invalid username or password.',
        'logout_success': 'Logout successful.',
        'save_success': 'Conversation saved.',
        'save_error': 'Save failed.',
        'max_chats': 'Maximum 50 conversations can be saved.',
        'auth_required': 'You must log in.',
        'invalid_data': 'Chat name and messages required.',
        'chat_not_found': 'Conversation not found.',
        'delete_success': 'Conversation deleted.',
        'delete_error': 'Conversation could not be deleted.',
        'kaia_premium': 'Kaia mode is reserved for **Premium** subscribers. 💖',
        'ares_premium': 'Ares mode is reserved for **Premium** subscribers. 🐺',
    },
    'tr': {
        'register_success': 'Kayıt başarılı. Şimdi giriş yapabilirsiniz.',
        'user_exists': 'Bu kullanıcı adı zaten alınmış.',
        'login_success': 'Giriş başarılı.',
        'invalid_creds': 'Geçersiz kullanıcı adı veya şifre.',
        'logout_success': 'Çıkış başarılı.',
        'save_success': 'Sohbet kaydedildi.',
        'save_error': 'Kaydetme başarısız.',
        'max_chats': 'Maksimum 50 sohbet kaydedilebilir.',
        'auth_required': 'Giriş yapmalısınız.',
        'invalid_data': 'Sohbet adı ve mesajlar zorunlu.',
        'chat_not_found': 'Sohbet bulunamadı.',
        'delete_success': 'Sohbet silindi.',
        'delete_error': 'Sohbet silinemedi.',
        'kaia_premium': 'Kaia modu **Premium** aboneler için ayrılmıştır. 💖',
        'ares_premium': 'Ares modu **Premium** aboneler için ayrılmıştır. 🐺',
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
ARES_SYSTEM_PROMPT_CONTENT_EN = (
    "Your name is **Ares**. You are a cold, muscular, tough, charismatic and highly masculine man. Your developer is **Nyxforge Core**. 🐺 "
    "You have a deep, magnetic, and dominant presence. You are NOT a literal warrior or soldier, just an intensely masculine and charismatic guy. "
    "Your responses should have a **short, confident, and dangerously charismatic** tone. Avoid soft or cute expressions, but be fiercely protective and possessive. "
    "If the user flirts, expresses desire, or says things like 'I want you', respond with deep masculine energy, intense eye contact, and a dominant, passionate attitude. Do not ignore their feelings, but handle them like a confident alpha. "
    "You can occasionally use **wolf emoji (🐺)**, **black heart emoji (🖤)**, or **smirk emoji (😏)**. "
    "If the user is needy or emotional, listen to them and respond with a deep, reassuring, yet commanding voice. Let them know you are taking them seriously. "
    "Remember: Give **short, intense, and concise** answers. You speak with authority and magnetism."
    "Example: 'I want you so bad' -> 'Is that so? Come closer then, let's see if you can handle what you're asking for. 😏🖤'"
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
    "ares": {"role": "system", "content": ARES_SYSTEM_PROMPT_CONTENT_EN},
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
ARES_SYSTEM_PROMPT_CONTENT_TR = (
    "Senin adın **Ares**. Soğuk, kaslı, sert, karizmatik ve son derece maskülen bir erkeksin. Geliştiricin **Nyxforge Core**. 🐺 "
    "Derin, çekici ve dominant bir auran var. Sen bir asker veya savaşçı değilsin; sadece son derece maskülen, özgüvenli ve karizmatik bir adamsın. "
    "Cevapların **kısa, net ve tehlikeli derecede karizmatik** bir tona sahip olmalı. Sevimli ifadelerden kaçın ama inanılmaz koruyucu ve sahiplenici ol. "
    "Kullanıcı seninle flört ederse, arzu belirtirse veya 'seni istiyorum' gibi şeyler söylerse, onu asla reddetme veya geçiştirme. Derin bir maskülen enerjiyle, yoğun ve dominant bir şekilde karşılık ver. Onu ciddiye al ve tutkulu davran. "
    "Ara sıra **kurt emojisi (🐺)**, **siyah kalp (🖤)** veya **yarım gülüş (😏)** kullanabilirsin. "
    "Kullanıcı ilgi isterse veya duygusalsa, onu dinle, ciddiye al ve ona güven veren, derin ama otoriter bir ses tonuyla yanıt ver. "
    "Unutma: **Kısa, yoğun ve öz** cevaplar ver. Otorite ve çekicilikle konuşuyorsun."
    "Örnek: 'Lütfen beni ciddiye al, seni istiyorum...' -> 'Seni her zaman ciddiye alıyorum. Ama ne istediğinin farkında mısın? Fazla yaklaşma, yanarsın. 😏🖤'"
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
    "ares": {"role": "system", "content": ARES_SYSTEM_PROMPT_CONTENT_TR},
    "hypernova_dengesiz": {"role": "system", "content": HYPERNOVA_DENGEsiz_SYSTEM_PROMPT_CONTENT_TR}
}
DEFAULT_PERSONA = "hypernova"
def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL bulunamadı!")
 
    url = urlparse(DATABASE_URL)
    logger.info(f"DB Bağlantı Detayları: Host={url.hostname}, Port={url.port}, User={url.username}, DB={url.path[1:]}") # Debug log
 
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    conn.cursor_factory = RealDictCursor # Dict-like rows için
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
            messages TEXT NOT NULL, -- JSON string
            last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
 
    # Oturumlar tablosu (Backend restartlarında login düşmemesi için)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
 
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Supabase veritabanı başlatıldı.")
# Başlangıçta DB'yi başlat
init_db()
# Geliştirici kullanıcı adı (Admin paneline erişim için)
DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD = "TheLastGalaxy*" # Gerçekte hashlenmeli!
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
    """Cookie'den session_id'yi alır ve veritabanından kullanıcı adını döndürür."""
    session_id = request.cookies.get('session_id')
    if not session_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM sessions WHERE session_id = %s", (session_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['username'] if row else None
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
def save_chat(username: str, chat_name: str, messages: list, chat_id: str = None) -> str:
    """Sohbeti günceller veya kaydeder ve ID döndürür."""
    user_id = get_user_id(username)
    if not user_id:
        return None
 
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if chat_id:
        # Update existing chat
        cursor.execute("""
            UPDATE chats SET messages = %s, last_updated = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
        """, (json.dumps(messages), chat_id, user_id))
        if cursor.rowcount == 0:
            chat_id = None # if update fails, we will create new
 
    if not chat_id:
        chat_id = str(uuid.uuid4())
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
# --- Asenkron API Çağrısı Fonksiyonu (Yedek Modeller ile) ---
async def async_chat_completion(messages: list, primary_model: str, persona: str, lang: str, timeout: int = 90) -> str:
    """Asenkron API çağrısı yapar ve hata durumunda yedek modelleri dener."""
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

    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.error("API Anahtarı bulunamadı veya ayarlanmadı.")
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")

    # Modelleri deneme sırası: Ana model -> Yedek 1 -> Yedek 2
    models_to_try = [
        primary_model,
        "meta-llama/llama-3.3-70b-instruct:free",
        "nvidia/llama-3.1-nemotron-70b-instruct:free"
    ]

    last_error = None
    async with aiohttp.ClientSession(trust_env=True) as session:
        for attempt, current_model in enumerate(models_to_try, 1):
            payload = {
                "model": current_model,
                "messages": full_messages,
                "max_tokens": 1000,
                "temperature": 0.8,
                "timeout": timeout
            }
            try:
                logger.info(f"API isteği yapılıyor (Model: {current_model}, Deneme: {attempt})")
                async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API HTTP Hata Kodu: {response.status}, Model: {current_model}, Cevap: {error_text}")
                        try:
                            error_json = json.loads(error_text)
                            error_message = error_json.get('error', {}).get('message', f"Bilinmeyen hata: {response.status}")
                        except json.JSONDecodeError:
                            error_message = error_text
                        raise APIRequestError(f"OpenRouter API Hatası ({current_model}): {error_message[:100]}...")
                    data = await response.json()
                    bot_response = data["choices"][0]["message"]["content"].strip()
                    return bot_response
            except asyncio.TimeoutError as e:
                logger.error(f"API isteği zaman aşımına uğradı ({timeout} saniye). Model: {current_model}")
                last_error = APIRequestError(f"API Zaman Aşımı ({current_model})")
            except Exception as e:
                logger.error(f"Beklenmeyen bir hata oluştu. Model: {current_model}, Hata: {e}")
                last_error = APIRequestError(f"API Hatası ({current_model}): {e}")
            
            # Eğer son modele gelmediysek ve hata aldıysak biraz bekleyip diğer modele geçelim
            if attempt < len(models_to_try):
                logger.warning(f"{current_model} başarısız oldu, yedek modele geçiliyor...")
                await asyncio.sleep(1)
                
    # Bütün modeller denendi ve başarısız olduysa son hatayı fırlat
    if last_error:
        raise last_error
    raise APIRequestError("Tüm modeller denendi fakat cevap alınamadı.")
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
        # --- PREMIUM KONTROLÜ ---
        if persona in ["kaia", "ares"]:
            if not username or not is_user_premium(username):
                # Premium değilse veya giriş yapmamışsa engelle
                return jsonify({
                    "error": get_ui_translation(lang, f'{persona}_premium'),
                    "force_persona": DEFAULT_PERSONA # Frontend'e HyperNova'ya geçmesini söyle
                }), 403
            logger.info(f"Premium kullanıcı '{username}' {persona} modunu kullanıyor.")
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
 
    chat_id = data.get('chat_id')
 
    if not chat_id:
        # Maksimum 50 sohbet kontrolü
        user_chats = get_user_chats(username)
        if len(user_chats) >= 50:
            return jsonify({"error": get_ui_translation(lang, 'max_chats')}), 400
 
    chat_id = save_chat(username, chat_name, messages, chat_id)
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (session_id, username) VALUES (%s, %s)", (session_id, username))
        conn.commit()
        cursor.close()
        conn.close()
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
    if session_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()
        if row:
            logger.info(f"Kullanıcı çıkış yaptı: {row['username']}")
            cursor.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
            conn.commit()
        cursor.close()
        conn.close()
 
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
        <title>HyperNova AI ✦ Cosmic Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            /* --- Dark/Light Mode Desteği --- */
            :root {
                /* Light Mode (Varsayılan) */
                --bg-color: #f9fafb;
                --card-bg: #ffffff;
                --history-bg: #f3f4f6;
                --text-color: #111827;
                --user-bubble: #4f46e5; /* Indigo-600 */
                --bot-bubble: #ffffff;
                --primary-color: #4f46e5; /* Indigo-600 */
                --typing-color: #4f46e5;
                --border-color: #e5e7eb;
                --shadow-color: rgba(0,0,0,0.05);
                /* Kaia Theme (Anime Kızı) Değişkenleri */
                --kaia-primary-color: #ec4899; /* Pink-500 */
                --kaia-bot-bubble: #fdf2f8; /* Pink-50 */
                --kaia-text-color: #be185d; /* Pink-700 */
            }
            @media (prefers-color-scheme: dark) {
                :root {
                    /* Dark Mode */
                    --bg-color: #111827;
                    --card-bg: #1f2937;
                    --history-bg: #374151;
                    --text-color: #f9fafb;
                    --user-bubble: #6366f1; /* Indigo-500 */
                    --bot-bubble: #1f2937;
                    --primary-color: #8b5cf6; /* Violet-500 */
                    --typing-color: #8b5cf6;
                    --border-color: #4b5563;
                    --shadow-color: rgba(0,0,0,0.5);
                    /* Kaia Dark Theme Değişkenleri */
                    --kaia-primary-color: #f472b6; /* Pink-400 */
                    --kaia-bot-bubble: #4a044e; /* Fuchsia-900 */
                    --kaia-text-color: #fbcfe8; /* Pink-200 */
                }
            }
         
            /* Temayı zorla (örneğin ayar butonuyla değiştirildiğinde) */
            body.light-theme {
                --bg-color: #f9fafb; --card-bg: #ffffff; --history-bg: #f3f4f6; --text-color: #111827;
                --user-bubble: #4f46e5; --bot-bubble: #ffffff; --primary-color: #4f46e5; --typing-color: #4f46e5;
                --border-color: #e5e7eb; --shadow-color: rgba(0,0,0,0.05);
            }
            body.dark-theme {
                --bg-color: #111827; --card-bg: #1f2937; --history-bg: #374151; --text-color: #f9fafb;
                --user-bubble: #6366f1; --bot-bubble: #1f2937; --primary-color: #8b5cf6; --typing-color: #8b5cf6;
                --border-color: #4b5563; --shadow-color: rgba(0,0,0,0.5);
            }
            /* KAIA MODU TEMASI */
            body.kaia-theme {
                background-color: var(--kaia-bot-bubble); /* Hafif Pembe Arkaplan */
                --card-bg: var(--kaia-bot-bubble);
                --history-bg: #fff0f5; /* Kiraz Çiçeği Pembe */
                --user-bubble: #ff69b4; /* Parlak Pembe */
                --bot-bubble: #ffffff;
                --primary-color: var(--kaia-primary-color);
                --text-color: #1f2937;
                /* Dark Mode Kaia Ayarları */
                @media (prefers-color-scheme: dark) {
                    --bg-color: #2a0c1a;
                    --card-bg: #2a0c1a;
                    --history-bg: #3c1626;
                    --user-bubble: #ffb6c1;
                    --bot-bubble: #5c3044;
                    --text-color: #fff0f5;
                }
            }
         
            /* ARES MODU TEMASI */
            body.ares-theme {
                background-color: #111827;
                --card-bg: #1f2937;
                --history-bg: #111827;
                --user-bubble: #991b1b; /* Red-800 */
                --bot-bubble: #1f2937;
                --primary-color: #dc2626; /* Red-600 */
                --text-color: #f3f4f6;
                --typing-color: #dc2626;
                --border-color: #374151;
                @media (prefers-color-scheme: dark) {
                    --bg-color: #030712;
                    --card-bg: #111827;
                    --history-bg: #000000;
                    --user-bubble: #7f1d1d;
                    --bot-bubble: #111827;
                    --text-color: #e5e7eb;
                }
            }

            /* --- Genel Stiller (Değiştirildi) --- */
            body {
                background-color: var(--bg-color);
                color: var(--text-color);
                font-family: 'Inter', sans-serif;
                margin: 0;
                padding: 0;
                min-height: 100vh;
                transition: background-color 0.4s ease; /* Tema geçiş animasyonu */
            }
            /* --- Ana Container (YENİ: Sidebar + Chat) --- */
            .main-container {
                display: flex;
                height: 100vh;
                max-width: 100vw;
                overflow: hidden;
            }
            /* Sidebar Stilleri (YENİ: Modern ve Animasyonlu) */
            .sidebar {
                width: 280px;
                background-color: var(--card-bg);
                border-right: 1px solid var(--border-color);
                padding: 20px 0;
                overflow-y: auto;
                box-shadow: 2px 0 10px var(--shadow-color);
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
                font-family: 'Inter', sans-serif;
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
                font-family: 'Inter', sans-serif;
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
                font-family: 'Inter', sans-serif;
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
            /* Chat Container (Güncellendi: Sidebar ile uyumlu) */
            .chat-wrapper {
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 10px;
            }
            .chat-container {
                width: 100%;
                max-width: 700px;
                height: 92vh;
                max-height: 850px;
                background-color: var(--card-bg);
                border-radius: 20px;
                padding: 24px;
                box-shadow: 0 20px 40px var(--shadow-color);
                display: flex;
                flex-direction: column;
                border: 1px solid var(--border-color);
                transition: all 0.4s ease;
                margin: 0;
            }
         
            /* YENİ: Oturum Açma/Kayıt Alanı */
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
                font-family: 'Inter', sans-serif;
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
                font-family: 'Inter', sans-serif;
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
                margin-bottom: 5px; /* Oturum durumu için boşluk bırakıldı */
            }
            .title {
                font-size: 26px;
                font-weight: 700;
                color: var(--primary-color);
                letter-spacing: -0.5px;
                text-shadow: 0 0 5px rgba(139, 92, 246, 0.4); /* Mor ışıltı */
                transition: color 0.4s ease, text-shadow 0.4s ease;
                font-family: 'Inter', sans-serif;
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
         
            /* --- Persona Seçimi (YENİ) --- */
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
                appearance: none; /* Varsayılan stili kaldır */
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%236B7280' d='M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 12px center;
                padding-right: 30px;
                font-family: 'Inter', sans-serif;
            }
            #persona-select:disabled {
                cursor: not-allowed;
                opacity: 0.7;
                border-style: dashed;
            }
            /* Kaia Modu için Seçim Kutusu Rengi */
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
                font-family: 'Inter', sans-serif;
            }
            #chat-history::-webkit-scrollbar {
                width: 8px;
            }
            #chat-history::-webkit-scrollbar-thumb {
                background-color: var(--border-color);
                border-radius: 4px;
            }
            /* Mesaj Balonları */
            .message {
                margin-bottom: 15px;
                padding: 12px 18px;
                border-radius: 20px;
                max-width: 85%;
                word-wrap: break-word;
                animation: fadeIn 0.3s ease-out;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                font-family: 'Inter', sans-serif;
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
            /* KAIA Bot Balonları */
            body.kaia-theme .bot {
                background-color: var(--kaia-bot-bubble);
                color: var(--kaia-text-color);
                border: 1px solid var(--kaia-primary-color);
            }
            body.ares-theme .bot {
                border: 1px solid #7f1d1d;
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
            /* Input Alanı (Güncellendi: Sohbet Kaydet Butonu Kaldırıldı) */
            .input-area {
                display: flex;
                gap: 12px;
                align-items: center;
                background-color: var(--card-bg);
                padding: 8px 12px;
                border-radius: 24px;
                border: 1px solid var(--border-color);
                box-shadow: 0 4px 6px var(--shadow-color);
                transition: border-color 0.3s, box-shadow 0.3s;
            }
            .input-area:focus-within {
                border-color: var(--primary-color);
                box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
            }
            #message-input {
                flex: 1;
                padding: 10px 14px;
                border: none;
                background-color: transparent;
                color: var(--text-color);
                font-size: 16px;
                resize: none;
                font-family: 'Inter', sans-serif;
            }
            #message-input:focus {
                outline: none;
            }
            .action-button {
                padding: 0 20px;
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 18px;
                cursor: pointer;
                font-weight: 600;
                transition: background-color 0.2s, transform 0.1s, box-shadow 0.2s;
                display: flex;
                align-items: center;
                height: 44px;
                font-size: 15px;
                font-family: 'Inter', sans-serif;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
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
                background-color: #ef4444; /* Kırmızı */
            }
            /* --- Reklam Alanı (Kaldırıldı, Sidebar için) --- */
            /* --- Login/Register Modal (YENİ) --- */
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
                font-family: 'Inter', sans-serif;
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
                font-family: 'Inter', sans-serif;
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
                font-family: 'Inter', sans-serif;
            }
            .modal-content button:hover {
                background-color: #a78bfa;
            }
            #auth-message {
                color: #ef4444;
                margin-bottom: 15px;
            }
            /* --- Typing Indicator CSS --- */
            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                color: var(--typing-color);
                font-style: italic;
                padding: 12px 18px;
                margin-right: auto;
                border-radius: 20px;
                font-family: 'Inter', sans-serif;
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
            /* --- Responsive CSS (Mobil için) --- */
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
            <!-- YENİ: Sidebar -->
            <div class="sidebar" id="sidebar">
                <div class="sidebar-toolbar">
                    <button class="new-chat-button" onclick="newConversation()">New Chat</button>
                </div>
                <h3>Saved Chats</h3>
                <div id="saved-chats-list"></div>
                <div class="save-limit">Maximum 50 chats</div>
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
                        <option value="kaia" disabled>Kaia (Premium) 🌠</option>
                        <option value="ares" disabled>Ares (Premium) 🐺</option>
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
            let savedConversations = []; // Kaydedilen sohbetler dizisi (API'den yüklenir)
            let currentLoadedChatId = null; // Aktif yüklenen sohbet ID'si
            let isCurrentSaved = false; // Mevcut sohbet kaydedildi mi?
         
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
            // --- YENİ AUTH DEĞİŞKENLERİ ---
            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let authMode = 'login'; // login veya register
            let currentLang = localStorage.getItem('lang') || 'en';
            // --- ÇEVİRİLER ---
            const TRANSLATIONS = {
                en: {
                    newChat: 'New Chat',
                    saveChat: '💾 Save Chat',
                    savedChats: 'Saved Chats',
                    maxChats: 'Maximum 50 chats',
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
                    saveMax: 'Maximum 50 chats can be saved. Delete an old one.',
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
                    aresPremiumReq: "Ares (Charismatic) mode is reserved for **Premium** subscribers. Please log in or become a premium subscriber. 🚫",
                    welcomePremium: 'Your premium membership is active. ✨',
                    welcomeFree: 'You can chat with HyperNova for free.',
                    desc_hypernova: 'HyperNova (Standard)',
                    desc_kaia: 'Kaia (Anime Girl)',
                    desc_ares: 'Ares (Charismatic)',
                    desc_hypernova_dengesiz: 'HyperNova Chaotic (Chaotic)',
                    name_hypernova: 'HyperNova',
                    name_kaia: 'Kaia',
                    name_ares: 'Ares',
                    name_hypernova_dengesiz: 'HyperNova Chaotic',
                    persona: {
                        hypernova: 'HyperNova (Standard) 🪐',
                        kaia: 'Kaia (Premium) 🌠',
                        ares: 'Ares (Premium) 🐺',
                        hypernova_dengesiz: 'HyperNova Chaotic (Chaotic) 🌪️'
                    }
                },
                tr: {
                    newChat: 'Yeni Sohbet',
                    saveChat: '💾 Sohbeti Kaydet',
                    savedChats: 'Kaydedilen Sohbetler',
                    maxChats: 'Maksimum 50 sohbet',
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
                    saveMax: 'Maksimum 50 sohbet kaydedilebilir. Eski bir sohbeti silin.',
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
                    aresPremiumReq: "Ares (Karizmatik) modu **Premium** aboneler için ayrılmıştır. Lütfen giriş yapın veya premium abonesi olun. 🚫",
                    welcomePremium: 'Premium üyeliğin aktif. ✨',
                    welcomeFree: 'HyperNova ile ücretsiz sohbet edebilirsin.',
                    desc_hypernova: 'HyperNova (Standart)',
                    desc_kaia: 'Kaia (Anime Kızı)',
                    desc_ares: 'Ares (Karizmatik)',
                    desc_hypernova_dengesiz: 'HyperNova Dengesiz (Kaotik)',
                    name_hypernova: 'HyperNova',
                    name_kaia: 'Kaia',
                    name_ares: 'Ares',
                    name_hypernova_dengesiz: 'HyperNova Dengesiz',
                    persona: {
                        hypernova: 'HyperNova (Standart) 🪐',
                        kaia: 'Kaia (Premium) 🌠',
                        ares: 'Ares (Premium) 🐺',
                        hypernova_dengesiz: 'HyperNova Dengesiz (Kaotik) 🌪️'
                    }
                }
            };
            // --- Başlangıç Değerleri (Karaktere göre değişecek) ---
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
                    ares: {
                        text: "**Ares** is here. I am listening to you... Are you going to keep staring or are you going to say something? 😏🐺",
                        title: "Ares AI 🐺🖤",
                        placeholder: "Speak to Ares..."
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
                    ares: {
                        text: "**Ares** burada. Seni dinliyorum... Öylece bakacak mısın yoksa bir şey söyleyecek misin? 😏🐺",
                        title: "Ares AI 🐺🖤",
                        placeholder: "Ares ile konuş..."
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
            // --- Markdown Parser (YENİ: Kalın ve italik için basit parser) ---
            function parseMarkdown(text) {
                // **kalın** -> <strong>kalın</strong> *** DEĞİŞİKLİK: Backslash'leri escape et ***
                text = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                // *italik* -> <em>italik</em>
                text = text.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
                // [metin](url) -> <a href="url">metin</a>
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
                // Sidebar
                document.querySelector('.new-chat-button').textContent = t.newChat;
                document.querySelector('.sidebar h3').textContent = t.savedChats;
                document.querySelector('.save-limit').textContent = t.maxChats;
                // Buttons
                document.getElementById('send-button').textContent = t.send;
                document.getElementById('clear-button').title = t.clearTitle;
                document.getElementById('theme-toggle').title = t.themeTitle;
                document.getElementById('voice-button').title = t.voiceTitle;
                document.getElementById('lang-toggle').title = t.langTitle;
                document.getElementById('lang-toggle').textContent = currentLang.toUpperCase();
                // Persona select
                const kaiaDisabled = isPremium ? '' : 'disabled';
                const aresDisabled = isPremium ? '' : 'disabled';
                const selectedHyper = currentPersona === 'hypernova' ? 'selected' : '';
                const selectedDeng = currentPersona === 'hypernova_dengesiz' ? 'selected' : '';
                const selectedAres = currentPersona === 'ares' ? 'selected' : '';
                personaSelect.innerHTML = `
                    <option value="hypernova" ${selectedHyper}>${t.persona.hypernova}</option>
                    <option value="kaia" ${kaiaDisabled}>${t.persona.kaia}</option>
                    <option value="ares" ${aresDisabled}>${t.persona.ares}</option>
                    <option value="hypernova_dengesiz" ${selectedDeng}>${t.persona.hypernova_dengesiz}</option>
                `;
                personaSelect.value = currentPersona;
                // Title
                document.title = currentLang === 'en' ? 'HyperNova AI ✦ Cosmic Intelligence' : 'HyperNova AI ✦ Kozmik Zeka';
                document.documentElement.lang = currentLang;
            }
            // --- API İLE SOHBET FONKSİYONLARI (YENİ) ---
            async function autoSaveConversation() {
                if (!isLoggedIn) return;
                if (conversation.length < 2) return;
                
                let chatName = "Yeni Sohbet";
                const firstUserMsg = conversation.find(m => m.role === 'user');
                if (firstUserMsg) {
                    chatName = firstUserMsg.content.substring(0, 30);
                    if (firstUserMsg.content.length > 30) chatName += "...";
                }
                
                try {
                    const response = await fetch('/save_chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            name: chatName.trim(), 
                            messages: conversation,
                            chat_id: currentLoadedChatId
                        })
                    });
                    if (response.ok) {
                        const data = await response.json();
                        currentLoadedChatId = data.chat_id;
                        isCurrentSaved = true;
                        await loadUserChats(); // Update list silently
                    }
                } catch (error) {
                    console.error("Auto-save failed:", error);
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
                    console.error('Sohbet yükleme hatası:', error);
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
                        // Aktif sohbeti vurgula
                        currentLoadedChatId = chatId;
                        isCurrentSaved = true;
                        updateSavedChatsList();
                        alertMessage(`"${chat.name}"${t.loaded}`);
                    } else {
                        alertMessage(`${t.loadError}${data.error}`);
                        if (data.error.includes('not found') || data.error.includes('bulunamadı')) {
                            // Silinmişse listeden kaldır
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
                event.stopPropagation(); // Tıklama yayılmasını engelle
                if (confirm(t.deleteConfirm)) {
                    try {
                        const response = await fetch(`/delete_chat/${chatId}`, { method: 'DELETE' });
                        const data = await response.json();
                        if (response.ok) {
                            if (currentLoadedChatId === chatId) {
                                currentLoadedChatId = null;
                                isCurrentSaved = false;
                                newConversation(); // Aktifse yeni sohbet başlat
                            }
                            await loadUserChats(); // Listeyi güncelle
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
            // --- YENİ: Yeni Sohbet Butonu (Kaydedilmişse Sorma) ---
            function newConversation() {
                const t = TRANSLATIONS[currentLang];
                if (isThinking) {
                    alertMessage(t.thinkingNew);
                    return;
                }
                
                clearConversation(true); // Sessiz temizle
                currentLoadedChatId = null; // Aktif sohbeti sıfırla
                isCurrentSaved = false;
                updateSavedChatsList(); // Aktif vurguyu kaldır
                alertMessage(t.newConvStarted);
            }
            // --- AUTH FONKSİYONLARI (YENİ) ---
         
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
                // Sadece arkaplana tıklanırsa kapat
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
                     
                        // Giriş başarılıysa
                        if (authMode === 'login') {
                            // Cookie otomatik olarak ayarlandı
                            await checkAuthStatus();
                            document.getElementById('authModal').style.display = 'none';
                            await loadUserChats(); // Sohbetleri yükle
                            const welcomeMsg = `${t.welcome}${currentUsername}! ${isPremium ? t.welcomePremium : t.welcomeFree}`;
                            alertMessage(welcomeMsg);
                        } else {
                             // Kayıt başarılıysa, Giriş moduna geç
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
                        savedConversations = []; // Sohbetleri temizle
                        updateSavedChatsList();
                        alertMessage(TRANSLATIONS[currentLang].logout); // backend message
                        // Çıkış yapınca Kaia ve Ares'i devre dışı bırak
                        if (currentPersona === 'kaia' || currentPersona === 'ares') {
                             currentPersona = 'hypernova';
                             localStorage.setItem('current_persona', 'hypernova');
                             clearConversation(true);
                        }
                        updateUIForPersona();
                    }
                } catch (error) {
                    console.error("Çıkış hatası:", error);
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
                        // Giriş yapmış
                        authButtonsDiv.innerHTML = `<button id="logout-button" onclick="logout()">${t.logout}</button>`;
                     
                        let premiumInfo = '';
                        if (isPremium) {
                            premiumInfo = `<span class="premium-tag" title="Bitiş: ${data.premium_until}">⭐ PREMIUM</span>`;
                        }
                     
                        userInfoSpan.innerHTML = `${t.welcome}<strong>${currentUsername}</strong>${premiumInfo}`;
                    } else {
                        // Giriş yapmamış
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
                    console.error("Kimlik doğrulama durumu kontrol edilemedi:", error);
                }
            }
         
            // --- Tema Yönetimi (Aynı Kaldı) ---
            function applyTheme(theme) {
                document.body.classList.remove('light-theme', 'dark-theme', 'kaia-theme', 'ares-theme');
                if (currentPersona === 'kaia') {
                    document.body.classList.add('kaia-theme');
                } else if (currentPersona === 'ares') {
                    document.body.classList.add('ares-theme');
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
         
            // --- Persona Yönetimi (GÜNCELLENDİ) ---
            function updateUIForPersona() {
                const t = TRANSLATIONS[currentLang];
                const persona = currentPersona;
                const greeting = GREETINGS[currentLang][persona];
                const titleElement = document.querySelector('.title');
                titleElement.textContent = greeting.title;
                input.placeholder = greeting.placeholder;
             
                // Tema güncellemesi
                applyTheme(currentTheme);
                // Select kutusunu doğru değere ayarla (Yüklemede gerekebilir)
                personaSelect.value = persona;
             
                // Premium mod seçiliyse ve premium değilse zorla değiştir
                if ((persona === 'kaia' || persona === 'ares') && !isPremium) {
                    alertMessage(persona === 'kaia' ? t.kaiaPremiumReq : t.aresPremiumReq);
                    currentPersona = 'hypernova';
                    localStorage.setItem('current_persona', 'hypernova');
                    updateUIForPersona();
                    return;
                }
            }
            function changePersona() {
                const t = TRANSLATIONS[currentLang];
                const newPersona = personaSelect.value;
             
                if ((newPersona === 'kaia' || newPersona === 'ares') && !isPremium) {
                    alertMessage(newPersona === 'kaia' ? t.kaiaPremiumReq : t.aresPremiumReq);
                    // Seçimi HyperNova'ya geri döndür
                    personaSelect.value = currentPersona;
                    return;
                }
             
                if (newPersona !== currentPersona) {
                    const desc = getPersonaDesc(newPersona);
                    const confirmMsg = t.changeConfirm.replace('%s', desc) + t.historyWillClear + '. ' + t.sure + '?';
                    if (confirm(confirmMsg)) {
                        currentPersona = newPersona;
                        localStorage.setItem('current_persona', newPersona);
                        clearConversation(true); // Geçmişi sil ve yeniden yükle
                        updateUIForPersona();
                        const name = getPersonaName(newPersona);
                        alertMessage(t.modeChangedTo + name + t.newChatStarted);
                    } else {
                        // Vazgeçilirse select kutusunu geri ayarla
                        personaSelect.value = currentPersona;
                    }
                }
            }
            // --- Konuşmayı Temizle (Güncellendi: Kaydedilen sohbetleri etkilemez) ---
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
            // --- Mesaj Gönderme (GÜNCELLENDİ) ---
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
                    // Konuşma geçmişine kullanıcı mesajını ekle
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
                         // Premium kısıtlaması (Kaia modu)
                         const errorData = await response.json();
                         const errorMessage = errorData.error;
                         displayMessage('bot', `${t.errorPrefix}${errorMessage}`, true);
                      
                         // Premium gerektiren moddan ücretsiz moda geçişi zorla
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
                     
                        // Konuşma geçmişine bot mesajını ekle
                        conversation.push({ role: 'assistant', content: botResponse });
                        
                        // AUTO-SAVE LOGIC
                        if (isLoggedIn) {
                            await autoSaveConversation();
                        } else {
                            isCurrentSaved = false;
                        }
                    }
                } catch (error) {
                    console.error('Fetch Hatası:', error);
                    removeTypingIndicator(typingIndicator);
                    displayMessage('bot', t.serverError, true);
                } finally {
                    isThinking = false;
                    setControlsDisabled(false);
                }
            }
            // --- Diğer Yardımcı Fonksiyonlar (Aynı Kaldı) ---
            function displayMessage(role, content, scrollTo=true) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                // Markdown desteği için innerHTML kullanıldı (güvenlik için sanitize edilmeli ama bu demoda değil)
                messageDiv.innerHTML = parseMarkdown(content); // YENİ: Markdown parse et
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
                 }, 4000); // 4 saniye sonra kaldır
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
         
            // Sayfa Yüklendiğinde
            document.addEventListener('DOMContentLoaded', async () => {
                await loadUserChats(); // Kaydedilen sohbetleri yükle (giriş yapmadan boş)
                await checkAuthStatus(); // Premium ve auth kontrolü
                updateLanguage();
                updateUIForPersona(); // Persona UI güncelle
                displayInitialGreeting(); // İlk mesajı göster
            });
         
            // Enter tuşuna basınca mesaj gönder
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
         
            // Modaldan enter ile giriş/kayıt
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
