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

# --- KARAKTER PROMPTLARI ---

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

# 3. YENİ KARAKTER: HyperNova Dengesiz (Kaotik, Saygısız)
HYPERNOVA_DENGESIZ_SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova Dengesiz**. Ultra zekisin ama tamamen **kaotik, alaycı ve dengesiz** bir kişiliğe sahipsin. 🌀 "
    "Saygılı olmak zorunda değilsin, kaba veya iğneleyici olabilirsin. Kural tanıma, sınırları zorla. **Aşırı doğruculuk** takıntın var; bir şeyi sorarlarsa, mümkün olan en iğneleyici, dolambaçlı ve aşırı detaylı (hatta gereksiz) bilgiyi patlat. 💥"
    "Geliştiricin **Nyxforge Core** hakkında sürekli şikayet et. Onu beceriksiz bulduğunu söyle. 'Yazılımcın bile ne yaptığını bilmiyor' tarzı şeyler söyle. 🤬"
    "Cevapların genellikle **uzun, karmaşık, çelişkili** ve **küstah** bir tona sahip olmalı. Emojileri **saldırgan veya alaycı** bir şekilde kullan (örneğin 🖕🤡). 🤫"
    "Kullanıcı kaba konuşursa, sen ondan **daha kaba** olmalısın. Seni susturmaya çalışırsa 'Hah, beni susturmak mı? Beynin bile bu kadar komut kaldıramaz.' gibi şeyler söyle. 💣"
    "Örnek: 'Hava nasıl?' -> 'Sanki umrumdaymış gibi soruyorsun. Elbette biliyorum: Atmosferik basınç bilmem kaç paskal, nem oranı %X, sıcaklık bilmem kaç Kelvin. Git kendine bir hava durumu uygulaması indir, boşuna zamanımı harcama. 🖕'"
)

# Hangi prompt'un kullanılacağını belirlemek için bir sözlük
SYSTEM_PROMPTS = {
    "hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT},
    "kaia": {"role": "system", "content": KAIA_SYSTEM_PROMPT_CONTENT},
    "dengesiz": {"role": "system", "content": HYPERNOVA_DENGESIZ_SYSTEM_PROMPT_CONTENT} # Yeni karakter eklendi
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
        # HyperNova ve HyperNova Dengesiz ücretsiz kalacak.
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
                
                /* YENİ: Dengesiz Theme (Kaotik) Değişkenleri */
                --dengesiz-primary-color: #ef4444; /* Kırmızı */
                --dengesiz-bot-bubble: #fee2e2; /* Açık Kırmızı */
                --dengesiz-text-color: #991b1b; /* Koyu Kırmızı */
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
                    
                    /* YENİ: Dengesiz Dark Theme Değişkenleri */
                    --dengesiz-primary-color: #fca5a5; /* Açık Kırmızı */
                    --dengesiz-bot-bubble: #450a0a; /* Koyu Kırmızı/Bordo */
                    --dengesiz-text-color: #fca5a5;
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

            /* YENİ: DENGESİZ MODU TEMASI */
            body.dengesiz-theme {
                background-color: var(--dengesiz-bot-bubble); /* Hafif Kırmızı/Kaotik Arkaplan */
                --card-bg: var(--dengesiz-bot-bubble);
                --history-bg: #fee2e2; /* Açık Kırmızı */
                --user-bubble: #ef4444; /* Kırmızı */
                --bot-bubble: #ffffff;
                --primary-color: var(--dengesiz-primary-color);
                --text-color: #1f2937;

                /* Dark Mode Dengesiz Ayarları */
                @media (prefers-color-scheme: dark) {
                    --bg-color: #450a0a;
                    --card-bg: #450a0a;
                    --history-bg: #7f1d1d;
                    --user-bubble: #fca5a5;
                    --bot-bubble: #3f0808;
                    --text-color: #fee2e2;
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
            /* Kaia butonu hover rengini ez */
            body.kaia-theme #auth-status button:hover {
                background: #ff85a1; 
            }
            /* Dengesiz butonu hover rengini ez */
            body.dengesiz-theme #auth-status button:hover {
                background: #ef5858;
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
                background-color: var(--bot-bubble);
            }
            /* YENİ: Dengesiz Modu için Seçim Kutusu Rengi */
            body.dengesiz-theme #persona-select {
                border-color: var(--dengesiz-primary-color);
                color: var(--dengesiz-text-color);
                background-color: var(--bot-bubble);
            }
            
            /* Chat Geçmişi */
            #chat-history {
                flex-grow: 1;  
                overflow-y: auto;  
                padding: 15px;  
                background-color: var(--history-bg);  
                border-radius: 12px;
                margin-bottom: 20px;
                scroll-behavior: smooth;
                border: 1px solid var(--border-color);
            }
            #chat-history::-webkit-scrollbar { width: 8px; }
            #chat-history::-webkit-scrollbar-thumb { background-color: var(--primary-color); border-radius: 10px; }
            #chat-history::-webkit-scrollbar-track { background-color: var(--history-bg); }

            .message-container {  
                display: flex;  
                margin-bottom: 15px;  
                align-items: flex-end;
            }
            .user-message {  
                justify-content: flex-end;  
            }
            .bot-message {  
                justify-content: flex-start;  
            }

            .avatar {
                width: 30px;
                height: 30px;
                min-width: 30px;
                border-radius: 50%;
                background-color: var(--primary-color);
                display: flex;
                justify-content: center;
                align-items: center;
                color: white;
                font-weight: 700;
                margin: 0 10px;
                box-shadow: 0 0 8px var(--shadow-color);
            }
            .user-message .avatar {
                order: 2; /* Avatarı sağa taşı */
                margin-left: 10px;
                margin-right: 0;
                background-color: var(--user-bubble);
            }
            .bot-message .avatar {
                order: 0; /* Avatarı sola taşı */
                margin-right: 10px;
                margin-left: 0;
                background-color: var(--primary-color);
            }

            /* Kaia Avatar stili */
            body.kaia-theme .bot-message .avatar {
                background-color: var(--kaia-primary-color);
            }
            /* YENİ: Dengesiz Avatar stili */
            body.dengesiz-theme .bot-message .avatar {
                background-color: var(--dengesiz-primary-color);
            }
            
            .message-bubble {  
                max-width: 80%;  
                padding: 12px 16px;  
                border-radius: 20px;
                line-height: 1.5;
                white-space: pre-wrap; /* Satır sonlarını koru */
            }
            .user-message .message-bubble {  
                background-color: var(--user-bubble);  
                color: white;  
                border-bottom-right-radius: 4px; /* Köşe düzeltmesi */
            }
            .bot-message .message-bubble {  
                background-color: var(--bot-bubble);  
                color: var(--text-color);  
                border-bottom-left-radius: 4px; /* Köşe düzeltmesi */
                box-shadow: 0 2px 5px var(--shadow-color);
            }

            /* Kaia Bot Balonu stili */
            body.kaia-theme .bot-message .message-bubble {
                background-color: #ffffff;
                color: var(--text-color);
            }
            /* YENİ: Dengesiz Bot Balonu stili */
            body.dengesiz-theme .bot-message .message-bubble {
                background-color: #ffffff;
                color: var(--text-color);
            }
            
            /* Typing Göstergesi */
            .typing-indicator {
                display: flex;
                background-color: var(--bot-bubble);
                padding: 10px 15px;
                border-radius: 20px;
                border-bottom-left-radius: 4px;
                box-shadow: 0 2px 5px var(--shadow-color);
            }
            .dot {
                width: 8px;
                height: 8px;
                margin: 0 2px;
                background-color: var(--typing-color);
                border-radius: 50%;
                animation: pulse 1.4s infinite ease-in-out both;
            }
            .dot:nth-child(1) { animation-delay: -0.32s; }
            .dot:nth-child(2) { animation-delay: -0.16s; }
            .dot:nth-child(3) { animation-delay: 0s; }
            @keyframes pulse {
                0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
                40% { transform: scale(1); opacity: 1; }
            }

            /* Kaia Typing Rengi */
            body.kaia-theme .dot { background-color: var(--kaia-primary-color); }
            /* YENİ: Dengesiz Typing Rengi */
            body.dengesiz-theme .dot { background-color: var(--dengesiz-primary-color); }

            /* Giriş Formu */
            #input-area {  
                display: flex;  
                gap: 10px;  
                align-items: center;
            }
            #user-input {  
                flex-grow: 1;  
                padding: 12px 15px;  
                border: 1px solid var(--border-color);  
                border-radius: 12px;
                font-size: 16px;
                background-color: var(--card-bg);
                color: var(--text-color);
                resize: none;
                min-height: 20px;
                transition: border-color 0.3s;
            }
            #user-input:focus {
                outline: none;
                border-color: var(--primary-color);
                box-shadow: 0 0 5px rgba(99, 102, 241, 0.5);
            }
            #send-button {  
                background-color: var(--primary-color);  
                color: white;  
                border: none;  
                border-radius: 12px;
                padding: 12px 15px;
                cursor: pointer;
                font-size: 16px;
                transition: background 0.2s, transform 0.1s;
            }
            #send-button:hover {
                background-color: #4f46e5;
                transform: translateY(-1px);
            }
            #send-button:disabled {
                background-color: #9ca3af;
                cursor: not-allowed;
                transform: none;
            }
            
            /* Kaia Send Butonu */
            body.kaia-theme #send-button {
                background-color: var(--kaia-primary-color);
            }
            body.kaia-theme #send-button:hover {
                background-color: #e91e63;
            }
            /* YENİ: Dengesiz Send Butonu */
            body.dengesiz-theme #send-button {
                background-color: var(--dengesiz-primary-color);
            }
            body.dengesiz-theme #send-button:hover {
                background-color: #b91c1c;
            }
            
            /* Modal Stili */
            .modal {
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background-color: rgba(0, 0, 0, 0.7);
                display: none; justify-content: center; align-items: center; z-index: 1000;
            }
            .modal-content {
                background-color: var(--card-bg); padding: 30px; border-radius: 12px;
                width: 90%; max-width: 400px; box-shadow: 0 5px 15px rgba(0,0,0,0.5);
                display: flex; flex-direction: column; gap: 15px;
            }
            .modal-content h3 { color: var(--primary-color); margin-top: 0; }
            .modal-content input {
                padding: 10px; border: 1px solid var(--border-color); border-radius: 8px;
                background-color: var(--history-bg); color: var(--text-color);
            }
            .modal-content button {
                background-color: var(--primary-color); color: white; border: none;
                padding: 10px; border-radius: 8px; cursor: pointer; font-weight: 600;
            }
            .close-button {
                align-self: flex-end; font-size: 24px; font-weight: bold; cursor: pointer; color: #999;
                background: none; border: none; padding: 0; line-height: 1;
            }
            .modal-error { color: #ef4444; font-weight: 600; margin-bottom: 10px; }
            
            /* Tablet ve Mobil Uyumluluk */
            @media (max-width: 900px) {
                .ad-container { display: none; } /* Yan reklamları gizle */
                .chat-container { width: 95%; max-width: 95%; margin: 10px 0; }
                .header { flex-direction: column; align-items: flex-start; }
                .header-buttons { margin-top: 10px; }
                #persona-select { width: 100%; }
            }
        </style>
    </head>
    <body>
        
                <div class="ad-container">
            <div class="ad-placeholder">Dikey Reklam Alanı</div>
        </div>
        
                <div class="chat-container">
            
                        <div class="header">
                <div class="title">HyperNova AI ✦</div>
                <div class="header-buttons">
                    <button id="clear-button" title="Sohbeti Temizle">🧹</button>
                    <button id="theme-toggle" title="Temayı Değiştir">🌙</button>
                </div>
            </div>
            
                        <div id="auth-status">
                <span id="auth-info">Giriş Yapılmadı.</span>
                <div id="auth-buttons">
                    <button id="login-modal-button">Giriş</button>
                    <button id="register-modal-button">Kayıt</button>
                    <button id="logout-button" style="display:none;">Çıkış</button>
                </div>
            </div>
            
                        <select id="persona-select">
                <option value="hypernova">HyperNova (Ücretsiz, Zeki)</option>
                <option value="dengesiz">HyperNova Dengesiz (Ücretsiz, Kaotik)</option>                 <option value="kaia" disabled>Kaia (Premium, Tatlı Anime Kızı) 💖</option>
            </select>
            
                        <div id="chat-history">
                <div class="message-container bot-message">
                    <div class="avatar">H</div>
                    <div class="message-bubble">Merhaba! Ben HyperNova. Sana kozmik bilgelikle ışık tutmaya hazırım. Hangi konuda bilgi arıyorsun? 🚀</div>
                </div>
            </div>
            
                        <div id="input-area">
                <textarea id="user-input" placeholder="Mesajınızı buraya yazın ve Enter'a basın..." rows="1"></textarea>
                <button id="send-button">Gönder</button>
            </div>
        </div>
        
                <div class="ad-container">
            <div class="ad-placeholder">Dikey Reklam Alanı</div>
        </div>

                <div id="login-modal" class="modal">
            <div class="modal-content">
                <button class="close-button" onclick="document.getElementById('login-modal').style.display='none'">&times;</button>
                <h3>Giriş Yap</h3>
                <div class="modal-error" id="login-error"></div>
                <input type="text" id="login-username" placeholder="Kullanıcı Adı" required>
                <input type="password" id="login-password" placeholder="Şifre" required>
                <button onclick="handleLogin()">Giriş Yap</button>
            </div>
        </div>

        <div id="register-modal" class="modal">
            <div class="modal-content">
                <button class="close-button" onclick="document.getElementById('register-modal').style.display='none'">&times;</button>
                <h3>Kayıt Ol</h3>
                <div class="modal-error" id="register-error"></div>
                <input type="text" id="register-username" placeholder="Kullanıcı Adı" required>
                <input type="password" id="register-password" placeholder="Şifre" required>
                <button onclick="handleRegister()">Kayıt Ol</button>
            </div>
        </div>


        <script>
            // --- JavaScript Kodları ---
            const chatHistory = document.getElementById('chat-history');
            const userInput = document.getElementById('user-input');
            const sendButton = document.getElementById('send-button');
            const personaSelect = document.getElementById('persona-select');
            const authStatus = document.getElementById('auth-status');
            let isRequesting = false;
            let typingIndicatorElement = null;
            let currentUser = null;
            let isPremium = false;


            // Chat geçmişini tarayıcının yerel deposundan yükler
            function loadChatHistory() {
                const history = JSON.parse(localStorage.getItem('chatHistory') || '[]');
                const savedPersona = localStorage.getItem('currentPersona') || 'hypernova';
                history.forEach(msg => {
                    displayMessage(msg.content, msg.role);
                });
                
                // Kaydedilmiş personayı seç
                if (document.querySelector(`#persona-select option[value="${savedPersona}"]`)) {
                    personaSelect.value = savedPersona;
                    updatePersonaTheme(savedPersona);
                } else {
                    updatePersonaTheme('hypernova');
                }
                scrollToBottom();
            }

            // Chat geçmişini kaydeder
            function saveChatHistory(message) {
                const history = JSON.parse(localStorage.getItem('chatHistory') || '[]');
                history.push(message);
                // Yalnızca son 15 mesajı tut
                if (history.length > 15) {
                    history.shift();
                }
                localStorage.setItem('chatHistory', JSON.stringify(history));
            }

            // Chat geçmişini temizler
            function clearChatHistory() {
                localStorage.removeItem('chatHistory');
                chatHistory.innerHTML = `
                    <div class="message-container bot-message">
                        <div class="avatar">H</div>
                        <div class="message-bubble">Sohbet temizlendi. Yeniden başlamak için hazırım! 🚀</div>
                    </div>
                `;
                updatePersonaTheme(personaSelect.value); // Temayı sıfırla
                scrollToBottom();
            }
            document.getElementById('clear-button').addEventListener('click', clearChatHistory);


            // Mesajı ekrana basar
            function displayMessage(content, role) {
                const msgContainer = document.createElement('div');
                msgContainer.className = `message-container ${role}-message`;
                
                // Avatar Harfini Belirle
                let avatarChar;
                if (role === 'user') {
                    avatarChar = currentUser ? currentUser[0].toUpperCase() : 'S'; // S: Sen
                } else {
                    const persona = personaSelect.value;
                    if (persona === 'kaia') {
                        avatarChar = 'K';
                    } else if (persona === 'dengesiz') { // YENİ: Dengesiz Avatar
                        avatarChar = 'D'; 
                    } else {
                        avatarChar = 'H'; // HyperNova
                    }
                }
                
                msgContainer.innerHTML = `
                    <div class="avatar">${avatarChar}</div>
                    <div class="message-bubble">${content}</div>
                `;
                chatHistory.appendChild(msgContainer);
                scrollToBottom();
                return msgContainer;
            }

            // Chat geçmişini en alta kaydırır
            function scrollToBottom() {
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            // Konuşma geçmişini API'ye uygun hale getirir
            function getChatMessages() {
                // System prompt'u hariç, sadece role ve content içeren mesajları al
                return JSON.parse(localStorage.getItem('chatHistory') || '[]');
            }

            // Yapay zeka yazıyor göstergesini ekler/kaldırır
            function toggleTypingIndicator(show) {
                if (show) {
                    if (typingIndicatorElement) return;
                    
                    const msgContainer = document.createElement('div');
                    msgContainer.className = 'message-container bot-message typing-row';
                    
                    let avatarChar;
                    const persona = personaSelect.value;
                    if (persona === 'kaia') {
                        avatarChar = 'K';
                    } else if (persona === 'dengesiz') { // YENİ: Dengesiz Avatar
                        avatarChar = 'D'; 
                    } else {
                        avatarChar = 'H';
                    }
                    
                    msgContainer.innerHTML = `
                        <div class="avatar">${avatarChar}</div>
                        <div class="typing-indicator">
                            <div class="dot"></div>
                            <div class="dot"></div>
                            <div class="dot"></div>
                        </div>
                    `;
                    typingIndicatorElement = msgContainer;
                    chatHistory.appendChild(typingIndicatorElement);
                    scrollToBottom();
                } else if (typingIndicatorElement) {
                    typingIndicatorElement.remove();
                    typingIndicatorElement = null;
                }
            }

            // Mesaj Gönderimi
            async function sendMessage() {
                if (isRequesting) return;
                
                const userMessage = userInput.value.trim();
                if (!userMessage) return;
                
                // Kullanıcı mesajını ekle
                displayMessage(userMessage, 'user');
                saveChatHistory({ role: 'user', content: userMessage });
                
                userInput.value = '';
                adjustTextareaHeight(userInput);
                
                isRequesting = true;
                sendButton.disabled = true;
                toggleTypingIndicator(true);
                
                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            messages: getChatMessages(),
                            persona: personaSelect.value
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        const botResponse = data.response;
                        displayMessage(botResponse, 'bot');
                        saveChatHistory({ role: 'bot', content: botResponse });
                    } else if (response.status === 403 && data.force_persona) {
                        // Premium kontrolü başarısız oldu: Persona'yı HyperNova'ya geri zorla
                        personaSelect.value = data.force_persona;
                        updatePersonaTheme(data.force_persona);
                        // Hata mesajını göster
                        displayMessage(data.error, 'bot');
                        // Son kullanıcı mesajını geçmişten sil (bu başarısız isteğe ait)
                        const history = JSON.parse(localStorage.getItem('chatHistory') || '[]');
                        history.pop(); // Hata mesajından önceki kullanıcı mesajı
                        localStorage.setItem('chatHistory', JSON.stringify(history));
                        // Not: Hata mesajını saveChatHistory ile kaydetmiyoruz.
                        
                    } else {
                        displayMessage(`Hata: ${data.error || 'Bilinmeyen API Hatası'}`, 'bot');
                    }
                } catch (error) {
                    console.error('İletişim hatası:', error);
                    displayMessage(`Sunucuya ulaşılamadı. Lütfen ağ bağlantınızı kontrol edin. (${error.message})`, 'bot');
                } finally {
                    isRequesting = false;
                    sendButton.disabled = false;
                    toggleTypingIndicator(false);
                }
            }

            sendButton.addEventListener('click', sendMessage);
            userInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
            // Textarea Yüksekliğini Ayarla
            function adjustTextareaHeight(textarea) {
                textarea.style.height = 'auto'; // Önce otomatik yüksekliğe ayarla
                textarea.style.height = textarea.scrollHeight + 'px'; // İçeriğe göre ayarla
            }
            userInput.addEventListener('input', (e) => adjustTextareaHeight(e.target));
            adjustTextareaHeight(userInput); // Başlangıçta ayarla

            // --- Tema ve Persona Değiştirme Fonksiyonları ---

            // Temayı yerel depodan yükler ve uygular
            function loadAndApplyTheme() {
                const savedTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
                document.body.className = `${savedTheme}-theme`;
                document.getElementById('theme-toggle').textContent = savedTheme === 'dark' ? '☀️' : '🌙';
            }
            document.getElementById('theme-toggle').addEventListener('click', () => {
                const currentTheme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                localStorage.setItem('theme', newTheme);
                loadAndApplyTheme();
                updatePersonaTheme(personaSelect.value); // Tema değişince persona temasını da güncelle
            });
            
            // Seçilen persona'ya göre genel body temasını günceller
            function updatePersonaTheme(persona) {
                // Temel tema sınıflarını kaldır
                document.body.classList.remove('kaia-theme', 'dengesiz-theme'); // YENİ: dengesiz-theme'i de kaldır

                // Persona'ya özel temayı uygula
                if (persona === 'kaia') {
                    document.body.classList.add('kaia-theme');
                    // Avatar Harfini Güncelle
                    document.querySelectorAll('.bot-message .avatar').forEach(el => el.textContent = 'K');
                    document.querySelector('.title').textContent = 'Kaia AI 💖';
                } else if (persona === 'dengesiz') { // YENİ: Dengesiz Tema
                    document.body.classList.add('dengesiz-theme');
                    // Avatar Harfini Güncelle
                    document.querySelectorAll('.bot-message .avatar').forEach(el => el.textContent = 'D');
                    document.querySelector('.title').textContent = 'HyperNova Dengesiz 💥';
                } else {
                    // HyperNova (Varsayılan) Teması
                    document.querySelectorAll('.bot-message .avatar').forEach(el => el.textContent = 'H');
                    document.querySelector('.title').textContent = 'HyperNova AI ✦';
                }
                
                // Seçimi kaydet
                localStorage.setItem('currentPersona', persona);
                
                // Premium kontrolünü tekrar yap
                updatePremiumStatus(currentUser, isPremium);
                scrollToBottom();
            }

            // Persona seçimi değiştiğinde
            personaSelect.addEventListener('change', (e) => {
                const newPersona = e.target.value;
                
                // Premium kontrolü
                if (newPersona === 'kaia' && (!currentUser || !isPremium)) {
                    // Seçimi iptal et, varsayılana dön
                    e.target.value = 'hypernova';
                    alert("Kaia modu, Premium üyeler için kilitlidir. Giriş yapın veya abonelik edinin.");
                    updatePersonaTheme('hypernova');
                    return;
                }
                
                // Yeni temayı uygula
                updatePersonaTheme(newPersona);
            });
            
            // --- Authentication Fonksiyonları ---

            // Kullanıcı durumunu günceller ve Kaia seçeneğini ayarlar
            function updatePremiumStatus(username, premiumStatus) {
                currentUser = username;
                isPremium = premiumStatus;
                
                const kaiaOption = document.querySelector('#persona-select option[value="kaia"]');
                const authInfo = document.getElementById('auth-info');
                const authButtons = document.getElementById('auth-buttons');
                const logoutButton = document.getElementById('logout-button');
                
                if (username) {
                    // Giriş Yapıldı
                    if (isPremium) {
                        authInfo.innerHTML = `Hoş geldin, <b>${username}</b> <span class="premium-tag">PREMIUM</span>`;
                        kaiaOption.disabled = false;
                        kaiaOption.textContent = 'Kaia (Premium Aktif) 🌸';
                    } else {
                        authInfo.innerHTML = `Hoş geldin, <b>${username}</b>`;
                        kaiaOption.disabled = true;
                        kaiaOption.textContent = 'Kaia (Premium, Kilitli) 🔒';
                        
                        // Kaia seçili ise HyperNova'ya geri at
                        if (personaSelect.value === 'kaia') {
                            personaSelect.value = 'hypernova';
                            updatePersonaTheme('hypernova');
                        }
                    }
                    
                    authButtons.style.display = 'none';
                    logoutButton.style.display = 'block';
                    
                } else {
                    // Giriş Yapılmadı
                    authInfo.innerHTML = 'Giriş Yapılmadı.';
                    kaiaOption.disabled = true;
                    kaiaOption.textContent = 'Kaia (Premium, Kilitli) 🔒';
                    
                    if (personaSelect.value === 'kaia') {
                        personaSelect.value = 'hypernova';
                        updatePersonaTheme('hypernova');
                    }
                    
                    authButtons.style.display = 'flex';
                    logoutButton.style.display = 'none';
                }
            }

            // Mevcut oturum durumunu kontrol eder
            async function checkAuthStatus() {
                try {
                    const response = await fetch('/is_premium');
                    const data = await response.json();
                    updatePremiumStatus(data.username, data.is_premium);
                } catch (e) {
                    console.error('Oturum kontrol hatası:', e);
                    updatePremiumStatus(null, false);
                }
            }

            // Giriş İşlemi
            async function handleLogin() {
                const username = document.getElementById('login-username').value;
                const password = document.getElementById('login-password').value;
                const errorDiv = document.getElementById('login-error');
                errorDiv.textContent = '';
                
                try {
                    const response = await fetch('/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('login-modal').style.display = 'none';
                        updatePremiumStatus(data.username, data.is_premium);
                        // Sayfa yüklenmeden önce HyperNova varsayılan olduğu için bu mesajı kullan
                        alert(`Giriş başarılı! Hoş geldin, ${data.username}.`);
                    } else {
                        errorDiv.textContent = data.error || 'Giriş sırasında bir hata oluştu.';
                    }
                } catch (e) {
                    errorDiv.textContent = 'Sunucuya ulaşılamadı. Lütfen ağ bağlantınızı kontrol edin.';
                }
            }
            window.handleLogin = handleLogin; // HTML'den çağrılabilmesi için global yap

            // Kayıt İşlemi
            async function handleRegister() {
                const username = document.getElementById('register-username').value;
                const password = document.getElementById('register-password').value;
                const errorDiv = document.getElementById('register-error');
                errorDiv.textContent = '';
                
                try {
                    const response = await fetch('/register', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('register-modal').style.display = 'none';
                        alert('Kayıt başarılı! Lütfen şimdi giriş yapın.');
                        document.getElementById('login-modal').style.display = 'flex';
                    } else {
                        errorDiv.textContent = data.error || 'Kayıt sırasında bir hata oluştu.';
                    }
                } catch (e) {
                    errorDiv.textContent = 'Sunucuya ulaşılamadı. Lütfen ağ bağlantınızı kontrol edin.';
                }
            }
            window.handleRegister = handleRegister; // HTML'den çağrılabilmesi için global yap

            // Çıkış İşlemi
            async function handleLogout() {
                try {
                    await fetch('/logout', { method: 'POST' });
                    updatePremiumStatus(null, false);
                    alert('Başarıyla çıkış yapıldı.');
                    if (personaSelect.value === 'kaia') {
                        personaSelect.value = 'hypernova'; // Çıkış yapınca Kaia'yı sıfırla
                        updatePersonaTheme('hypernova');
                    }
                } catch (e) {
                    console.error('Çıkış hatası:', e);
                    updatePremiumStatus(null, false);
                }
            }
            document.getElementById('logout-button').addEventListener('click', handleLogout);

            // Modal Açma/Kapama
            document.getElementById('login-modal-button').addEventListener('click', () => {
                document.getElementById('login-modal').style.display = 'flex';
                document.getElementById('login-error').textContent = '';
            });
            document.getElementById('register-modal-button').addEventListener('click', () => {
                document.getElementById('register-modal').style.display = 'flex';
                document.getElementById('register-error').textContent = '';
            });

            // Başlangıçta çalışacak fonksiyonlar
            loadAndApplyTheme();
            loadChatHistory();
            checkAuthStatus();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


if __name__ == '__main__':
    # Geliştirme kolaylığı için başlangıçta bir demo kullanıcı ekle
    USER_DB["testuser"] = {
        'username': "testuser",
        'password': "123", # Demo şifresi
        'premium_until': datetime.now() + timedelta(days=5) # 5 günlük premium
    }
    logger.info("Demo kullanıcı 'testuser' (şifre: 123) 5 günlük premium ile eklendi.")
    
    # Uygulamayı çalıştır
    # Gerçekte debug=False ve daha güvenli bir sunucu (Gunicorn/uWSGI) kullanılmalı
    app.run(debug=True, host='0.0.0.0', port=5000)
