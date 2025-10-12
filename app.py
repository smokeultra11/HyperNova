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
#   'username': str, 
#   'password': str (demo için düz metin), 
#   'premium_until': datetime,
#   'session_id': str (varsa)
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


            /* Input Alanı */
            .input-area {  
                display: flex;  
                gap: 10px;
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

            /* --- Reklam Alanı (YENİ) --- */
            #ad-banner {
                height: 40px;
                background-color: rgba(255, 200, 0, 0.2); /* Hafif sarı/altın rengi */
                color: #8a6c08;
                text-align: center;
                line-height: 40px;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
                margin-top: 5px;
                cursor: pointer;
                transition: background-color 0.3s;
                /* REKLAM: Premium'a geçişi teşvik eden bir banner */
            }
            #ad-banner:hover {
                background-color: rgba(255, 200, 0, 0.3);
            }
            .ad-hidden {
                display: none;
            }


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
            @media (max-width: 900px) { /* Reklamları gizlemek için breakpoint yükseltildi */
                .ad-container {
                    display: none; /* Yan reklamları mobil/dar ekranda gizle */
                }
            }
            @media (max-width: 640px) {
                body {
                    padding: 0;
                    align-items: stretch;
                }
                .chat-container {
                    width: 100%;
                    height: 100vh;
                    padding: 15px;
                    border-radius: 0;
                    box-shadow: none;
                    margin: 0; /* Reklamlar gizlendiği için margin kaldırıldı */
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
                #ad-banner {
                    height: 30px;
                    line-height: 30px;
                    font-size: 11px;
                }
            }
        </style>
    </head>
    <body>
        
        <div id="authModal" class="modal" onclick="closeModal(event)">
            <div class="modal-content">
                <h3 id="modalTitle">Oturum Aç</h3>
                <p id="auth-message" style="display: none;"></p>
                <input type="text" id="authUsername" placeholder="Kullanıcı Adı" required>
                <input type="password" id="authPassword" placeholder="Şifre" required>
                <button onclick="handleAuth()">Oturum Aç</button>
                <button style="background-color: #10b981; margin-top: 15px;" onclick="switchAuthMode()">Kayıt Ol'a Geç</button>
            </div>
        </div>
        
        <div class="ad-container" id="left-ad-container">
            <div class="ad-placeholder">
                SOL REKLAM <br> 150x600
            </div>
        </div>

        <div class="chat-container">
            <div class="header">
                <div class="title">HyperNova AI 🪐✨</div>
                <div class="header-buttons">
                    <button id="clear-button" onclick="clearConversation()" title="Sohbeti Temizle ve Sıfırla">🧹</button>
                    <button id="theme-toggle" onclick="toggleTheme()" title="Temayı Değiştir">☀️</button>
                </div>
            </div>
            
            <div id="auth-status">
                <span id="user-info">Giriş Yapılmadı</span>
                <div id="auth-buttons">
                    <button onclick="showModal('login')">Giriş Yap</button>
                    <button onclick="showModal('register')">Kayıt Ol</button>
                    <button id="logout-button" style="display: none;" onclick="logout()">Çıkış Yap</button>
                </div>
            </div>
            
            <select id="persona-select" onchange="changePersona()">
                <option value="hypernova">HyperNova (Standart) 🪐</option>
                <option value="kaia" disabled>Kaia (Anime Kızı) 💖 (Premium)</option>
            </select>

            <div id="chat-history">
            </div>
            
            <div id="ad-banner" class="ad-visible" onclick="alert('Premium'a geçmek için Discord sunucumuzdan bilgi edinebilirsin! "https://discord.gg/J4h6zbHpYq"')">
                ✨ Reklamsız Deneyim ve Özel Kaia Temaları için Premium'a Geç! ✨
            </div>
            
            <div class="input-area">
                <input type="text" id="message-input" placeholder="Kozmik bir soru sor..." onkeypress="if(event.key==='Enter') sendMessage()">
                <button id="voice-button" class="action-button" onclick="toggleVoiceInput()" title="Sesli Giriş">🎙️</button>
                <button id="send-button" class="action-button" onclick="sendMessage()">Gönder</button>
            </div>
        </div>
        
        <div class="ad-container" id="right-ad-container">
            <div class="ad-placeholder">
                SAĞ REKLAM <br> 150x600
            </div>
        </div>

        <script>
            let conversation = [];
            let isThinking = false;
            let isVoiceListening = false;
            
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');
            const voiceButton = document.getElementById('voice-button');
            const themeToggle = document.getElementById('theme-toggle');
            const clearButton = document.getElementById('clear-button');
            const personaSelect = document.getElementById('persona-select');
            const adBanner = document.getElementById('ad-banner');
            const kaiaOption = personaSelect.querySelector('option[value="kaia"]');

            // --- YENİ AUTH DEĞİŞKENLERİ ---
            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let authMode = 'login'; // login veya register

            // --- Başlangıç Değerleri (Karaktere göre değişecek) ---
            const GREETINGS = {
                'hypernova': {
                    text: "**HyperNova** burada. Evrensel veri tabanına erişimi olan yapay zekayım. 🌌 Ne öğrenmek istediğini açıkça belirt. Kesin ve doğru bilgi aktarmaya odaklıyım. ✨",
                    title: "HyperNova AI 🪐✨",
                    placeholder: "Kozmik bir soru sor..."
                },
                'kaia': {
                    text: "**Kaia** seninle! 💖 Bugün nasılsın? Bana her şeyi sorabilirsin, sana en tatlı şekilde cevap vereceğim! Hemen başlayalım mı? 🌸",
                    title: "Kaia AI 💖🌸",
                    placeholder: "Kaia'ya tatlı bir şey söyle..."
                }
            };

            let currentPersona = localStorage.getItem('current_persona') || 'hypernova';
            let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

            // --- AUTH FONKSİYONLARI (YENİ) ---
            
            function showModal(mode) {
                authMode = mode;
                document.getElementById('modalTitle').textContent = mode === 'login' ? 'Oturum Aç' : 'Kayıt Ol';
                document.querySelector('.modal-content button:first-of-type').textContent = mode === 'login' ? 'Oturum Aç' : 'Kayıt Ol';
                document.querySelector('.modal-content button:last-of-type').textContent = mode === 'login' ? "Kayıt Ol'a Geç" : "Giriş Yap'a Geç";
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
                const username = document.getElementById('authUsername').value.trim();
                const password = document.getElementById('authPassword').value;
                const messageElement = document.getElementById('auth-message');
                
                messageElement.style.display = 'none';
                
                if (!username || !password) {
                    messageElement.textContent = 'Kullanıcı adı ve şifre boş olamaz.';
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
                            alertMessage(`Hoş geldin, ${currentUsername}! ${isPremium ? 'Premium üyeliğin aktif. ✨' : 'HyperNova ile ücretsiz sohbet edebilirsin.'}`);
                        } else {
                             // Kayıt başarılıysa, Giriş moduna geç
                            switchAuthMode();
                        }
                    } else {
                        messageElement.textContent = `Hata: ${data.error}`;
                        messageElement.style.color = '#ef4444';
                        messageElement.style.display = 'block';
                    }
                    
                } catch (error) {
                    messageElement.textContent = 'Ağ Hatası. Lütfen tekrar deneyin.';
                    messageElement.style.color = '#ef4444';
                    messageElement.style.display = 'block';
                }
            }
            
            async function logout() {
                try {
                    const response = await fetch('/logout', { method: 'POST' });
                    if (response.ok) {
                        await checkAuthStatus();
                        alertMessage('Başarıyla çıkış yaptın. Güle güle! 👋');
                        // Çıkış yapınca Kaia'yı devre dışı bırak
                        if (currentPersona === 'kaia') {
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
                    
                    const authStatusDiv = document.getElementById('auth-status');
                    const userInfoSpan = document.getElementById('user-info');
                    const authButtonsDiv = document.getElementById('auth-buttons');
                    
                    if (isLoggedIn) {
                        // Giriş yapmış
                        authButtonsDiv.innerHTML = `<button id="logout-button" onclick="logout()">Çıkış Yap</button>`;
                        
                        let premiumInfo = '';
                        if (isPremium) {
                            premiumInfo = `<span class="premium-tag" title="Bitiş: ${data.premium_until}">⭐ PREMIUM</span>`;
                            kaiaOption.removeAttribute('disabled');
                            kaiaOption.textContent = 'Kaia (Anime) 💖';
                            adBanner.classList.add('ad-hidden');
                            document.querySelectorAll('.ad-placeholder').forEach(el => el.textContent = 'Reklamsız Bölge ✨');
                        } else {
                            kaiaOption.setAttribute('disabled', 'disabled');
                            kaiaOption.textContent = 'Kaia (Anime) 💖 (Premium)';
                            adBanner.classList.remove('ad-hidden');
                            document.querySelectorAll('.ad-placeholder').forEach(el => el.textContent = 'REKLAM 150x600');
                        }
                        
                        userInfoSpan.innerHTML = `Hoş geldin, <strong>${currentUsername}</strong>${premiumInfo}`;

                    } else {
                        // Giriş yapmamış
                        userInfoSpan.innerHTML = 'Giriş Yapılmadı';
                        authButtonsDiv.innerHTML = `
                            <button onclick="showModal('login')">Giriş Yap</button>
                            <button onclick="showModal('register')">Kayıt Ol</button>
                        `;
                        isPremium = false;
                        kaiaOption.setAttribute('disabled', 'disabled');
                        kaiaOption.textContent = 'Kaia (Anime) 💖 (Premium)';
                        adBanner.classList.remove('ad-hidden');
                        document.querySelectorAll('.ad-placeholder').forEach(el => el.textContent = 'REKLAM 150x600');
                    }
                    
                } catch (error) {
                    console.error("Kimlik doğrulama durumu kontrol edilemedi:", error);
                }
            }
            

            // --- Tema Yönetimi (Aynı Kaldı) ---
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
            
            // --- Persona Yönetimi (GÜNCELLENDİ) ---
            function updateUIForPersona() {
                const persona = currentPersona;
                const greeting = GREETINGS[persona];
                const titleElement = document.querySelector('.title');

                titleElement.textContent = greeting.title;
                input.placeholder = greeting.placeholder;
                
                // Tema güncellemesi
                applyTheme(currentTheme);

                // Select kutusunu doğru değere ayarla (Yüklemede gerekebilir)
                personaSelect.value = persona;
                
                // Kaia seçiliyse HyperNova seçeneği devre dışı bırakılamaz
                if (persona === 'kaia' && !isPremium) {
                    // Bu senaryo sadece kullanıcı elle local storage'ı değiştirirse olur. 
                    // Normalde checkAuthStatus Kaia'yı devre dışı bırakır ve changePersona HyperNova'ya döner.
                    // Yine de bir önlem:
                    alertMessage("Bu mod Premium gerektirir. HyperNova'ya geçiliyor.");
                    currentPersona = 'hypernova';
                    localStorage.setItem('current_persona', 'hypernova');
                    updateUIForPersona();
                    return;
                }
            }

            function changePersona() {
                const newPersona = personaSelect.value;
                
                if (newPersona === 'kaia' && !isPremium) {
                    alertMessage("Kaia (Anime Kızı) modu **Premium** aboneler için ayrılmıştır. Lütfen giriş yapın veya premium abonesi olun. 🚫");
                    // Seçimi HyperNova'ya geri döndür
                    personaSelect.value = currentPersona; 
                    return;
                }
                
                if (newPersona !== currentPersona) {
                    if (confirm(`Modu ${newPersona === 'kaia' ? 'Kaia (Anime Kızı)' : 'HyperNova (Standart)'} olarak değiştirmek üzeresin. Geçmiş silinecek. Emin misin?`)) {
                        currentPersona = newPersona;
                        localStorage.setItem('current_persona', newPersona);
                        clearConversation(true); // Geçmişi sil ve yeniden yükle
                        updateUIForPersona();
                        alertMessage(`Mod ${currentPersona === 'kaia' ? 'Kaia' : 'HyperNova'} olarak değiştirildi. Yeni sohbet başlatıldı!`);
                    } else {
                        // Vazgeçilirse select kutusunu geri ayarla
                        personaSelect.value = currentPersona;
                    }
                }
            }


            // --- Konuşmayı Temizle (Aynı Kaldı) ---
            function clearConversation(isSilent = false) {
                if (isThinking) {
                    if (!isSilent) alertMessage('Sıfırlama işlemi için bekle, sistem meşgul. ⏳');
                    return;
                }
                
                if (isSilent || confirm('Konuşma geçmişi silinecek. Emin misin? 🤔')) {
                    conversation = [];
                    localStorage.removeItem('hypernova_chat_history_' + currentPersona); // Persona'ya özel geçmişi sil
                    historyDiv.innerHTML = '';
                    displayInitialGreeting();
                    if (!isSilent) alertMessage('Sohbet geçmişi silindi. Sıfırdan başlıyoruz. ✅');
                }
            }

            // --- Local Storage ve History Yönetimi (Aynı Kaldı) ---
            function saveHistory() {
                try {
                    const limitedHistory = conversation.slice(-20);  
                    localStorage.setItem('hypernova_chat_history_' + currentPersona, JSON.stringify(limitedHistory));
                } catch (e) {
                    console.warn("Local storage kaydı başarısız oldu.", e);
                }
            }

            function loadHistory() {
                checkAuthStatus().then(() => { // Önce kullanıcı ve premium durumu yüklensin
                    updateUIForPersona(); // UI'ı doğru persona/premium durumuna göre ayarla

                    try {
                        const savedHistory = localStorage.getItem('hypernova_chat_history_' + currentPersona);
                        historyDiv.innerHTML = '';
                        
                        if (savedHistory) {
                            const history = JSON.parse(savedHistory);
                            history.forEach(msg => {
                                if (msg.role !== 'system') {
                                    displayMessage(msg.role, msg.content, false);
                                }
                            });
                            conversation = history;
                            
                            // Eğer geçmişte bot mesajı yoksa ilk karşılamayı göster
                            if (conversation.length === 0 || conversation.every(msg => msg.role === 'user')) {
                                displayInitialGreeting();
                            }
                            scrollToBottom();
                        } else {
                            displayInitialGreeting();
                        }
                    } catch (e) {
                        console.error("Local storage yüklenirken hata:", e);
                        displayInitialGreeting();
                    }
                });
            }
            
            function displayInitialGreeting() {
                const greetingText = GREETINGS[currentPersona].text;
                displayMessage('bot', greetingText, false);
                conversation = [{role: 'bot', content: greetingText}];
                saveHistory();
            }

            // --- Mesaj Gönderme (GÜNCELLENDİ) ---
            async function sendMessage() {
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
                    saveHistory();

                    const apiMessages = conversation.map(msg => ({ role: msg.role, content: msg.content }));
                    
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ messages: apiMessages, persona: currentPersona }),
                    });

                    removeTypingIndicator(typingIndicator);
                    
                    if (response.status === 403) {
                         // Premium kısıtlaması (Kaia modu)
                         const errorData = await response.json();
                         const errorMessage = errorData.error;
                         displayMessage('bot', `**HATA:** ${errorMessage}`, true);
                         
                         // Premium gerektiren moddan ücretsiz moda geçişi zorla
                         if (errorData.force_persona === 'hypernova' && currentPersona === 'kaia') {
                              currentPersona = 'hypernova';
                              localStorage.setItem('current_persona', 'hypernova');
                              updateUIForPersona();
                              clearConversation(true);
                              alertMessage("Kaia modu Premium gerektirdiği için HyperNova'ya geçildi.");
                         }
                         
                    } else if (!response.ok) {
                        const errorData = await response.json();
                        displayMessage('bot', `**HATA:** Yapay zeka ile bağlantı kurulamadı. Lütfen kısa bir süre sonra tekrar deneyin. (${errorData.error || 'Bilinmeyen Hata'})`, true);
                    } else {
                        const data = await response.json();
                        const botResponse = data.response;
                        displayMessage('bot', botResponse, true);
                        
                        // Konuşma geçmişine bot mesajını ekle ve kaydet
                        conversation.push({ role: 'assistant', content: botResponse });
                        saveHistory();
                    }

                } catch (error) {
                    console.error('Fetch Hatası:', error);
                    removeTypingIndicator(typingIndicator);
                    displayMessage('bot', '**HATA:** Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edin. ⚠️', true);
                } finally {
                    isThinking = false;
                    setControlsDisabled(false);
                    // Hatanın ardından gönderilen user mesajını history'den temizle (kullanıcı tekrar denesin diye)
                    // if (conversation.length > 0 && conversation[conversation.length - 1].role === 'user') {
                    //     conversation.pop();
                    //     saveHistory();
                    // }
                }
            }


            // --- Diğer Yardımcı Fonksiyonlar (Aynı Kaldı) ---

            function displayMessage(role, content, scrollTo=true) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                // Markdown desteği için innerHTML kullanıldı (güvenlik için sanitize edilmeli ama bu demoda değil)
                messageDiv.innerHTML = content; 
                historyDiv.appendChild(messageDiv);
                if (scrollTo) {
                    scrollToBottom();
                }
            }
            
            function displayTypingIndicator() {
                const typingDiv = document.createElement('div');
                typingDiv.className = 'message bot typing-indicator';
                typingDiv.innerHTML = `
                    <span>Yazıyor...</span>
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
                 document.head.appendChild(style);
            }
            
            function toggleVoiceInput() {
                alertMessage("Sesli giriş özelliği bu demoda aktif değil. 🎤");
            }
            

            // Sayfa Yüklendiğinde
            document.addEventListener('DOMContentLoaded', () => {
                loadHistory(); // Premium kontrolü burada tetiklenir
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
    # Geliştirici kullanıcıyı önceden kaydet (in-memory demo için)
    # Bu veritabanı boşsa ilk kez sunucu başladığında çalışır.
    if DEVELOPER_USERNAME not in USER_DB:
        USER_DB[DEVELOPER_USERNAME] = {
            'username': DEVELOPER_USERNAME,
            'password': DEVELOPER_PASSWORD,
            'premium_until': datetime.now() + timedelta(days=9999) # Geliştirici her zaman premium
        }
        logger.info(f"Geliştirici kullanıcısı '{DEVELOPER_USERNAME}' sisteme eklendi.")
        
    app.run(debug=True, host='0.0.0.0', port=5000)
