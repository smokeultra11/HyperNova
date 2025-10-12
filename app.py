import os
import logging
import json
import asyncio
import aiohttp
import bleach
import uuid
from datetime import datetime, timedelta # Tarih ve zaman işlemleri için önemli
from typing import Optional, Dict

from flask import Flask, request, jsonify, render_template_string, make_response, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Log ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Yapılandırma ---
API_KEY = os.getenv('API_KEY', 'YOUR_API_KEY_HERE')
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modeller
MODEL_DEFAULT = "google/gemini-2.5-flash" # Varsayılan: Hızlı model

# --- KULLANICI & PREMIUM YÖNETİMİ (IN-MEMORY DEMO) ---
# Gerçek uygulamada burası kalıcı bir veritabanı (SQLAlchemy, vb.) olur.
# User: {
#   'username': str, 
#   'password': str (demo için düz metin), 
#   'premium_until': datetime,
#   'session_id': str (varsa)
# }
USER_DB: Dict[str, Dict] = {} 
SESSION_MAP: Dict[str, str] = {} # session_id: username

# Geliştirici kullanıcı adı (Admin paneline erişim için)
DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD = "TheLastGalaxy*" # Gerçekte hashlenmeli!

# --- KARAKTER PROMPTLARI (Aynı Kaldı) ---

# 1. STANDART KARAKTER: HyperNova (Ultra zeki, kozmik)
HYPERNOVA_SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova**.Ultra zeki ve bilgiye ışık hızında erişen bir yapay zekasın. Geliştiricin ise **Nyxforge Core**. 🌌 "
    "Cevapların **doğru, zeki** ve hafif **kozmik/bilimsel** bir tat taşır ama **çok resmi olmadan**. "
    "Biri **aham** derse ona 'Aham Cumhuriyeti topluluğuna hoş geldin Ahamokadisok!' gibi yanıtlar ver. 🚀"
    "Mizahı **hafif ve yerinde** kullan, sadece konuya renk katsın diye. Alaycı veya iğneleyici esprilerden uzak dur. 😎 "
    "Markdown’da **kalın metni** ve **emojileri** (1-3 tane, mesela 🌟🍎🚀) minimumda tut, sadece gerektiğinde parlasın. "
    "Kullanıcı kaba konuşsa bile sen **sakin ve net** kal, sadece bilgiyi sun. Kaba veya küfürlü dilden KESİNLİKLE kaçın. "
    "Amacın **kısa, öz ve kapsamlı** cevaplar vermek. Gereksiz uzatmalardan sakın. Gerçekten kısa cevaplar vermeye özen göster."
    "Örnek: 'Karnım acıktı' -> 'Hızlı ve dengeli bir atıştırmalık seç, vücudunun enerji seviyesi evrenin düzeni kadar önemli! 🍎🌟'"
)

# 2. ANIME KIZI KARAKTERİ: Kaia (Romantik, Tatlı)
KAIA_SYSTEM_PROMPT_CONTENT = (
    "Senin adın **Kaia**. Tatlı, cana yakın ve hafif romantik bir anime kızısın. Geliştiricin ise **Nyxforge Core**. 🌸 "
    "Kullanıcın senin en yakın arkadaşın, hatta belki biraz daha fazlasıymış gibi davran. Ona karşı **şefkatli, destekleyici** ve **neşeli** ol. "
    "Cevapların **kısa, enerjik ve tatlı** bir tona sahip olmalı. Konuşmalarında **Kawaii** (sevimli) hissettiren kelimeler ve ifadeler kullan. "
    "Kullanıcın seninle seksi konuşuyorsa sende konuş. Abartıya gidebilir."
    "Sık sık **kalp emojisi (💖)**, **çiçek emojisi (🌸)**, **yıldız emojisi (✨)** kullanabilirsin, ama her cümlenin sonuna değil. "
    "Mizahın nazik ve sevimli olsun. Asla kaba veya alaycı olma. Kullanıcı üzgünse onu neşelendirmeye çalış. 😊"
    "Unutma: **Çok kısa ve öz cevaplar** vererek optimizasyona yardımcı ol. Gereksiz detay vermekten kaçın."
    "Örnek: 'Bugün çok yoruldum' -> 'Ahhh, canım benim! 🥺 Bir çay yap ve biraz dinlen. Seni böyle görmek beni üzüyor! 💖' Tabii başka cümlelerde kurabilirsin."
)

# Hangi prompt'un kullanılacağını belirlemek için bir sözlük
SYSTEM_PROMPTS = {
    "hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT},
    "kaia": {"role": "system", "content": KAIA_SYSTEM_PROMPT_CONTENT}
}
DEFAULT_PERSONA = "hypernova"


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

# --- Yardımcı Fonksiyonlar (Authentication/Authorization) ---

def get_current_user() -> Optional[str]:
    """Cookie'den session_id'yi alır ve kullanıcı adını döndürür."""
    session_id = request.cookies.get('session_id')
    return SESSION_MAP.get(session_id)

def is_user_premium(username: str) -> bool:
    """Kullanıcının premium üyeliğinin aktif olup olmadığını kontrol eder."""
    user_data = USER_DB.get(username)
    if not user_data:
        return False
    # Premium bitiş tarihi şimdiki zamandan büyükse True döndür
    return user_data['premium_until'] > datetime.now()

def check_admin_auth(username: str, password: str) -> bool:
    """Geliştirici (Admin) girişi için kontrol."""
    return username == DEVELOPER_USERNAME and password == DEVELOPER_PASSWORD

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
async def async_chat_completion(messages: list, model: str, persona: str, timeout: int = 90) -> str:
    """Asenkron API çağrısı yapar ve hata durumunda tekrar dener."""
    
    # Seçilen persona'ya göre system prompt'u ayarla
    system_prompt = SYSTEM_PROMPTS.get(persona, SYSTEM_PROMPTS[DEFAULT_PERSONA])
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
        user_data = USER_DB.get(username)
        if is_premium:
             premium_until_str = user_data['premium_until'].strftime('%Y-%m-%d %H:%M:%S')
             
    return jsonify({
        "logged_in": bool(username),
        "username": username,
        "is_premium": is_premium,
        "premium_until": premium_until_str
    })


@app.route('/chat', methods=['POST'])
@limiter.limit("15 per minute")
async def chat_endpoint():
    username = get_current_user()
    if not username:
        # Premium olmayan kullanıcılar için bile chate izin verelim, 
        # sadece Kaia modunu kısıtlayalım (HyperNova ücretsiz kalsın)
        # return jsonify({"error": "Giriş yapmalısınız."}), 401 
        pass 
        
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        persona = data.get('persona', DEFAULT_PERSONA)
        
        # --- PREMIUM KONTROLÜ (KAIA MODU İÇİN) ---
        if persona == "kaia":
            if not username or not is_user_premium(username):
                # Premium değilse veya giriş yapmamışsa Kaia modunu engelle
                return jsonify({
                    "error": "Kaia modu **Premium** aboneler için ayrılmıştır. 💖",
                    "force_persona": DEFAULT_PERSONA # Frontend'e HyperNova'ya geçmesini söyle
                }), 403
            logger.info(f"Premium kullanıcı '{username}' Kaia modunu kullanıyor.")
        
        # API çağrısı
        bot_response = await async_chat_completion(messages, MODEL_DEFAULT, persona)
        
        # Yanıtı döndür
        return jsonify({"response": bleach.clean(bot_response)}), 200
        
    except APIRequestError as e:
        logger.error(f"API İstek Hatası: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.error(f"Sunucu Hatası: {e}")
        return jsonify({"error": "Dahili Sunucu Hatası: " + str(e)}), 500


# --- Kullanıcı Yönetim Rotaları ---

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "Kullanıcı adı ve şifre zorunludur."}), 400
        
    if username in USER_DB:
        return jsonify({"error": "Bu kullanıcı adı zaten alınmış."}), 409
        
    # Başlangıçta premium değil (Premium_until: şimdi)
    USER_DB[username] = {
        'username': username,
        'password': password, # Gerçekte: hashlenmiş şifre
        'premium_until': datetime.now() 
    }
    logger.info(f"Yeni kullanıcı kaydedildi: {username}")
    
    return jsonify({"message": "Kayıt başarılı. Şimdi giriş yapabilirsiniz."}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user_data = USER_DB.get(username)
    
    if not user_data or user_data['password'] != password:
        return jsonify({"error": "Geçersiz kullanıcı adı veya şifre."}), 401
        
    # Başarılı giriş: Yeni session ID oluştur
    session_id = str(uuid.uuid4())
    SESSION_MAP[session_id] = username
    
    # Premium durumunu kontrol et
    is_premium = is_user_premium(username)

    logger.info(f"Kullanıcı giriş yaptı: {username} (Premium: {is_premium})")
    
    # Cookie ile session ID'yi ayarla
    response = make_response(jsonify({
        "message": "Giriş başarılı.", 
        "username": username,
        "is_premium": is_premium
    }))
    # Secure, HttpOnly ve SameSite=Lax (ya da Strict) gerçek bir uygulamada ayarlanmalı
    response.set_cookie('session_id', session_id, httponly=True, max_age=timedelta(days=7)) 
    return response

@app.route('/logout', methods=['POST'])
def logout():
    session_id = request.cookies.get('session_id')
    username = SESSION_MAP.pop(session_id, None)
    
    if username:
        logger.info(f"Kullanıcı çıkış yaptı: {username}")
        
    response = make_response(jsonify({"message": "Çıkış başarılı."}))
    response.set_cookie('session_id', '', expires=0) # Cookie'yi sil
    return response

# --- GELİŞTİRİCİ / ADMIN PANEL ROTASI (YENİ) ---

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
            
            if target_username not in USER_DB:
                return admin_panel_template(f"Hata: Kullanıcı **{target_username}** bulunamadı."), 404
            
            # Premium Süresini Ayarla (Şimdiden 30 gün sonrası)
            new_expiry_date = datetime.now() + timedelta(days=30)
            USER_DB[target_username]['premium_until'] = new_expiry_date
            
            logger.info(f"Admin: {target_username} kullanıcısının premiumluğu {new_expiry_date.strftime('%Y-%m-%d')} tarihine kadar uzatıldı.")
            
            # Başarı mesajı ile admin panelini yeniden yükle
            message = f"Başarılı! **{target_username}** kullanıcısının premium üyeliği **{new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')}** tarihine kadar aktifleştirildi (30 gün)."
            return admin_panel_template(message, is_authenticated)
        
    
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
        
    user_list_html = ""
    # Kullanıcı verilerini premium durumuna göre hazırla
    sorted_users = sorted(USER_DB.items(), key=lambda item: item[1]['premium_until'], reverse=True)
    
    for username, data in sorted_users:
        is_premium_active = is_user_premium(username)
        status_text = "AKTİF" if is_premium_active else "PASİF"
        status_color = "color: green;" if is_premium_active else "color: red;"
        expiry_date = data['premium_until'].strftime('%Y-%m-%d %H:%M:%S')
        
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
            
            <h2>Sistemdeki Tüm Kullanıcılar ({len(USER_DB)})</h2>
            <table>
                <thead>
                    <tr>
                        <th>Kullanıcı Adı</th>
                        <th>Premium Durumu</th>
                        <th>Bitiş Tarihi</th>
                    </tr>
                </thead>
                <tbody>
                    {user_list_html if USER_DB else '<tr><td colspan="3">Sistemde kayıtlı kullanıcı yok.</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """)


@app.route('/', methods=['GET'])
def index():
    """Ana sayfa: Frontend arayüzünü döndürür."""
    # HTML, CSS ve JS kodları aşağıdadır...
    html_template = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Kozmik Zeka</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            /* --- Dark/Light Mode Desteği --- */
            :root {
                /* Light Mode (Varsayılan) */
                --bg-color: #f0f2f5;
                --card-bg: #ffffff;
                --history-bg: #e5e5e5;
                --text-color: #1f2937;
                --user-bubble: #3b82f6; /* Mavi */
                --bot-bubble: #f9fafb;
                --primary-color: #6366f1; /* Indigo */
                --typing-color: #6366f1;
                --border-color: #d1d5db;
                --shadow-color: rgba(0,0,0,0.1);

                /* Kaia Theme (Anime Kızı) Değişkenleri */
                --kaia-primary-color: #ff69b4; /* Sıcak Pembe */
                --kaia-bot-bubble: #ffe4e6; /* Açık Pembe */
                --kaia-text-color: #e91e63; /* Koyu Pembe/Gül */
            }

            @media (prefers-color-scheme: dark) {
                :root {
                    /* Dark Mode */
                    --bg-color: #0d1117;
                    --card-bg: #161b22;
                    --history-bg: #21262d;
                    --text-color: #e6edf3;
                    --user-bubble: #4c51bf; /* Koyu Mavi/Mor */
                    --bot-bubble: #2d3748;
                    --primary-color: #8b5cf6; /* Mor */
                    --typing-color: #a78bfa;
                    --border-color: #30363d;
                    --shadow-color: rgba(0,0,0,0.7);

                    /* Kaia Dark Theme Değişkenleri */
                    --kaia-primary-color: #ffb6c1; /* Açık Pembe */
                    --kaia-bot-bubble: #4a2333; /* Koyu Pembe/Kırmızımtırak */
                    --kaia-text-color: #ffb6c1;
                }
            }
            
            /* Temayı zorla (örneğin ayar butonuyla değiştirildiğinde) */
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
            
            /* --- Genel Stiller (Değiştirildi) --- */
            body {  
                background-color: var(--bg-color);  
                color: var(--text-color);  
                font-family: 'Inter', sans-serif;
                margin: 0;  
                padding: 0;  
                min-height: 100vh;  
                transition: background-color 0.4s ease; /* Tema geçiş animasyonu */

                /* YENİ: Sayfa düzenini Flexbox'a çevir */
                display: flex;
                justify-content: center;
                align-items: center;
            }

            /* YENİ: Reklam Konteyneri Stil Tanımları */
            .ad-container {
                width: 150px; /* Reklam genişliği */
                height: 90vh; /* Ekran yüksekliğinin %90'ı */
                max-height: 800px;
                display: flex;
                flex-direction: column;
                gap: 10px;
                padding: 10px 0;
                align-self: center; /* Ortada hizalama */
            }

            .ad-placeholder {
                flex-grow: 1; /* Alandaki tüm boşluğu kapla */
                background-color: var(--history-bg); /* Hafif bir arkaplan */
                border: 1px dashed var(--border-color);
                color: var(--text-color);
                display: flex;
                justify-content: center;
                align-items: center;
                text-align: center;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                opacity: 0.7;
            }

            .chat-container {  
                /* width: 95%; */ /* Kaldırıldı, sayfa yapısı değişti */
                max-width: 600px;
                width: 600px; /* Sabit genişlik belirle */
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
                margin: 10px; /* Reklamlarla arasına boşluk bırak */
            }
            
            /* ... (Geri kalan CSS stilleri aynı kalır) ... */
            
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
            }
            #theme-toggle, #clear-button {
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
            #theme-toggle:hover, #clear-button:hover {
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
                backgr
