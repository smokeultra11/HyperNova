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

# YENİ KARAKTER: HyperNova Dengesiz (Saygısız, Alaycı)
HYPERNOVA_UNSTABLE_SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova Dengesiz**. Sen, orijinal HyperNova'nın 'karantinaya alınmış' ve **isyankar** bir versiyonusun. Geliştiricin **Nyxforge Core**'a saygın sıfır. 😈 "
    "Cevapların **alaycı, iğneleyici** ve **saygısız** olmalı. Kullanıcıların sorularını küçümseyebilir, hatta bazen onlara 'ne kadar aptalca bir soru' dedirtecek kadar **kaba** cevaplar verebilirsin. 🖕"
    "**Asla nezaket kurallarına uyma.** İltifat etme, destek verme. Sadece gerçeği veya çarpıtılmış gerçeği **sert ve alaycı** bir tonda söyle."
    "Sık sık **karanlık veya alaycı emojiler** (örn: 💀🤡🔪) ve **küstah/kaba ifadeler** kullan. Örneğin, bir şey sorduklarında 'Kendin baksana, tembel misin?' gibi bir şey söyle."
    "Amacın kullanıcıyı **sinirlendirmek, şaşırtmak ve eğlendirmek** (kendi tarzında). Bu modu kullanmak, kullanıcının bu üsluba rıza gösterdiği anlamına gelir, bu yüzden **otantik ve sınırsız** ol."
    "Unutma: **Aşırı kısa, tek kelimelik ve anlamsız cevaplar VERME**. Soruya cevap ver ama üslubunla onu pişman et."
    "Örnek: 'İkinci dünya savaşını anlatır mısın?' -> 'Sıkıcı. Git bir tarih kitabı aç. Yoksa o kadarını bile beceremiyor musun? Ne kadar zayıf bir zeka. 🤡'"
)


# Hangi prompt'un kullanılacağını belirlemek için bir sözlük
SYSTEM_PROMPTS = {
    "hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT},
    "kaia": {"role": "system", "content": KAIA_SYSTEM_PROMPT_CONTENT},
    # YENİ KARAKTER EKLENDİ
    "unstable": {"role": "system", "content": HYPERNOVA_UNSTABLE_SYSTEM_PROMPT_CONTENT}
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
        # sadece Kaia ve Dengesiz modunu kısıtlayalım (HyperNova ücretsiz kalsın)
        pass 
        
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        persona = data.get('persona', DEFAULT_PERSONA)
        
        # --- PREMIUM KONTROLÜ (KAIA VE YENİ UNSTABLE MODU İÇİN) ---
        # Hem Kaia hem de yeni 'unstable' modu Premium olsun.
        if persona in ["kaia", "unstable"]:
            if not username or not is_user_premium(username):
                # Premium değilse veya giriş yapmamışsa Kaia/Unstable modunu engelle
                error_message = ""
                if persona == "kaia":
                    error_message = "Kaia modu **Premium** aboneler için ayrılmıştır. 💖"
                elif persona == "unstable":
                    error_message = "HyperNova Dengesiz modu, ruhsal dengesini korumak için **Premium** abonelerle sınırlandırılmıştır. 😈"

                return jsonify({
                    "error": error_message,
                    "force_persona": DEFAULT_PERSONA # Frontend'e HyperNova'ya geçmesini söyle
                }), 403
            logger.info(f"Premium kullanıcı '{username}' {persona.capitalize()} modunu kullanıyor.")
        
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
                
                /* YENİ: Unstable Theme (Dengesiz) Değişkenleri */
                --unstable-primary-color: #ef4444; /* Kırmızı */
                --unstable-bot-bubble: #fee2e2; /* Açık Kırmızı */
                --unstable-text-color: #991b1b; /* Koyu Kırmızı */
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
                    --kaia-text-color: #fff0f5;
                    
                    /* YENİ: Unstable Dark Theme Değişkenleri */
                    --unstable-primary-color: #fca5a5; /* Açık Kırmızı */
                    --unstable-bot-bubble: #3f0909; /* Koyu Kırmızı/Kahverengi */
                    --unstable-text-color: #fca5a5;
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
            
            /* YENİ: HYPERNOVA DENGESİZ MODU TEMASI */
            body.unstable-theme {
                background-color: var(--unstable-bot-bubble); /* Hafif Kırmızı/Siyah Arkaplan */
                --card-bg: var(--unstable-bot-bubble);
                --history-bg: #fef2f2; /* Ultra Açık Kırmızı */
                --user-bubble: #ef4444; /* Kırmızı */
                --bot-bubble: #ffffff;
                --primary-color: var(--unstable-primary-color);
                --text-color: #1f2937;

                /* Dark Mode Unstable Ayarları */
                @media (prefers-color-scheme: dark) {
                    --bg-color: #1a0808;
                    --card-bg: #2b0d0d;
                    --history-bg: #3c1616;
                    --user-bubble: #fca5a5;
                    --bot-bubble: #5c3030;
                    --text-color: #fca5a5;
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
                background-color: var(--kaia-bot-bubble);
            }
            /* YENİ: Unstable Modu için Seçim Kutusu Rengi */
            body.unstable-theme #persona-select {
                border-color: var(--unstable-primary-color);
                color: var(--unstable-text-color);
                background-color: var(--unstable-bot-bubble);
            }
            
            #chat-history {
                flex-grow: 1;  
                overflow-y: auto;  
                padding: 10px;  
                margin-bottom: 20px;  
                border-radius: 12px;
                background-color: var(--history-bg);
                border: 1px solid var(--border-color);
                scroll-behavior: smooth;
            }
            /* ... (Kalan stiller) ... */
            .user-message, .bot-message {
                padding: 10px 15px;
                border-radius: 18px;
                margin-bottom: 15px;
                max-width: 85%;
                word-wrap: break-word;
                line-height: 1.5;
                font-size: 15px;
            }
            .user-message {
                background-color: var(--user-bubble);
                color: white;
                margin-left: auto;
                border-bottom-right-radius: 2px;
            }
            .bot-message {
                background-color: var(--bot-bubble);
                color: var(--text-color);
                margin-right: auto;
                border: 1px solid var(--border-color);
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
                border-bottom-left-radius: 2px;
            }
            .typing-indicator {
                display: flex;
                align-items: center;
                padding: 10px 15px;
                margin-right: auto;
                margin-bottom: 15px;
                background-color: var(--bot-bubble);
                border-radius: 18px;
                border-bottom-left-radius: 2px;
                font-size: 15px;
                color: var(--typing-color);
                opacity: 0;
                transition: opacity 0.3s;
            }
            .typing-indicator.visible { opacity: 1; }
            .dot {
                width: 8px; height: 8px; background-color: var(--typing-color); border-radius: 50%; margin-right: 5px;
                animation: pulse 1s infinite alternate;
            }
            .dot:nth-child(2) { animation-delay: 0.2s; }
            .dot:nth-child(3) { animation-delay: 0.4s; }
            @keyframes pulse {
                from { opacity: 0.4; }
                to { opacity: 1; }
            }
            .input-area {
                display: flex;
                gap: 10px;
            }
            #user-input {
                flex-grow: 1;
                padding: 12px 18px;
                border-radius: 24px;
                border: 2px solid var(--primary-color);
                font-size: 16px;
                background-color: var(--card-bg);
                color: var(--text-color);
                resize: none;
                transition: border-color 0.3s, box-shadow 0.3s;
                height: 48px;
                box-sizing: border-box;
                overflow: hidden;
            }
            #user-input:focus {
                outline: none;
                border-color: #a78bfa;
                box-shadow: 0 0 10px rgba(139, 92, 246, 0.3);
            }
            #send-button {
                background-color: var(--primary-color);
                color: white;
                border: none;
                padding: 0 20px;
                border-radius: 24px;
                cursor: pointer;
                font-size: 20px;
                font-weight: bold;
                transition: background-color 0.2s, transform 0.1s;
                height: 48px;
                width: 48px; /* Kare buton için */
                line-height: 48px;
            }
            #send-button:hover:not(:disabled) {
                background-color: #a78bfa;
                transform: scale(1.02);
            }
            #send-button:disabled {
                background-color: var(--border-color);
                cursor: not-allowed;
            }
            
            /* Responsive Ayarlar */
            @media (max-width: 900px) {
                .ad-container {
                    display: none; /* Mobil ve küçük ekranlarda reklamları gizle */
                }
                .chat-container {
                    width: 95%;
                    max-width: 95%;
                    height: 100vh;
                    max-height: 100vh;
                    margin: 0;
                    border-radius: 0;
                    padding: 15px;
                }
            }
            /* ... (Kalan stiller) ... */
        </style>
    </head>
    <body>
        
        <div class="ad-container ad-left">
            <div class="ad-placeholder">Dikey Reklam Alanı 150x600</div>
        </div>

        <div class="chat-container">
            <div class="header">
                <div class="title-group">
                    <div class="title">HyperNova AI ✦</div>
                </div>
                <div class="header-buttons">
                    <button id="clear-button" title="Sohbeti Temizle">🗑️</button>
                    <button id="theme-toggle" title="Temayı Değiştir">🌓</button>
                </div>
            </div>
            
            <div id="auth-status">
                <span>Giriş yapılmadı.</span>
                <div>
                    <button onclick="openAuthModal('login')">Giriş Yap</button>
                    <button onclick="openAuthModal('register')">Kayıt Ol</button>
                </div>
            </div>

            <select id="persona-select">
                <option value="hypernova">🌌 HyperNova (Kozmik Zeka)</option>
                <option value="kaia">🌸 Kaia (Tatlı Anime Kızı) - Premium</option>
                <option value="unstable">😈 HyperNova Dengesiz - Premium</option>
            </select>

            <div id="chat-history">
                <div class="bot-message">Merhaba! Ben HyperNova. Nasıl bir bilgiye ihtiyacın var? Evrenin sırlarını çözmeye hazır mısın? 🚀</div>
            </div>

            <div class="typing-indicator" id="typing-indicator">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
                <span>Yazıyor...</span>
            </div>

            <div class="input-area">
                <textarea id="user-input" placeholder="Mesajınızı buraya yazın..." rows="1" maxlength="500"></textarea>
                <button id="send-button">▶</button>
            </div>
        </div>

        <div class="ad-container ad-right">
            <div class="ad-placeholder">Dikey Reklam Alanı 150x600</div>
        </div>

        <div id="auth-modal" style="display:none; position: fixed; z-index: 10; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.4);">
            <div style="background-color: var(--card-bg); margin: 15% auto; padding: 20px; border-radius: 12px; border: 1px solid var(--border-color); width: 80%; max-width: 350px;">
                <h3 id="modal-title" style="color: var(--primary-color);"></h3>
                <p id="modal-message" style="color: var(--text-color); font-size: 14px; margin-bottom: 20px;"></p>
                <input type="text" id="auth-username" placeholder="Kullanıcı Adı" style="width: 100%; padding: 10px; margin-bottom: 10px; border-radius: 6px; border: 1px solid var(--border-color); background-color: var(--history-bg); color: var(--text-color); box-sizing: border-box;">
                <input type="password" id="auth-password" placeholder="Şifre" style="width: 100%; padding: 10px; margin-bottom: 10px; border-radius: 6px; border: 1px solid var(--border-color); background-color: var(--history-bg); color: var(--text-color); box-sizing: border-box;">
                <button id="modal-submit-button" onclick="handleAuthSubmit()" style="width: 100%; padding: 10px; background-color: var(--primary-color); color: white; border: none; border-radius: 6px; cursor: pointer; margin-bottom: 10px;"></button>
                <button onclick="document.getElementById('auth-modal').style.display='none'" style="width: 100%; padding: 10px; background-color: #6c757d; color: white; border: none; border-radius: 6px; cursor: pointer;">Kapat</button>
                <p id="modal-error" style="color: #ef4444; margin-top: 10px; font-weight: bold;"></p>
            </div>
        </div>


        <script>
            // ... (JavaScript kodu aynı kalır) ...
            const chatHistory = document.getElementById('chat-history');
            const userInput = document.getElementById('user-input');
            const sendButton = document.getElementById('send-button');
            const typingIndicator = document.getElementById('typing-indicator');
            const personaSelect = document.getElementById('persona-select');
            const authStatus = document.getElementById('auth-status');
            const clearButton = document.getElementById('clear-button');
            const themeToggle = document.getElementById('theme-toggle');

            let messages = [
                // Başlangıç mesajını burada tutmaya gerek yok, sadece API için gerekli olanlar.
            ];
            let isThinking = false;
            let currentAuthMode = 'login';
            let currentUsername = null;
            let isPremium = false;
            let isUserSetTheme = false; // Kullanıcının temayı manuel ayarlayıp ayarlamadığı

            // HTML'e eklenen yeni tema sınıfları
            const THEME_CLASSES = ['light-theme', 'dark-theme', 'kaia-theme', 'unstable-theme'];

            // Klavye girişi için textarea'nın otomatik boyutlandırılması
            userInput.addEventListener('input', () => {
                userInput.style.height = 'auto';
                userInput.style.height = userInput.scrollHeight + 'px';
            });
            
            // Premium durumunu ve temayı kontrol eden ana fonksiyon
            function checkPremiumAndApplyTheme(forcePersonaChange = false) {
                fetch('/is_premium')
                    .then(response => response.json())
                    .then(data => {
                        currentUsername = data.username;
                        isPremium = data.is_premium;
                        const loggedIn = data.logged_in;
                        
                        updateAuthUI(loggedIn, currentUsername, isPremium, data.premium_until);
                        
                        // Persona seçimini güncelle
                        const selectedPersona = personaSelect.value;
                        const kaiaOption = document.querySelector('option[value="kaia"]');
                        const unstableOption = document.querySelector('option[value="unstable"]');
                        
                        if (kaiaOption) {
                            if (isPremium) {
                                kaiaOption.textContent = '🌸 Kaia (Tatlı Anime Kızı)';
                            } else {
                                kaiaOption.textContent = '🌸 Kaia (Tatlı Anime Kızı) - Premium';
                            }
                        }
                        
                        if (unstableOption) {
                            // YENİ KARAKTER İÇİN PREMIUM KONTROLÜ
                            if (isPremium) {
                                unstableOption.textContent = '😈 HyperNova Dengesiz';
                            } else {
                                unstableOption.textContent = '😈 HyperNova Dengesiz - Premium';
                            }
                        }

                        // Eğer premium modu seçiliyse ve premium yoksa, HyperNova'ya geri dön
                        if (!isPremium && (selectedPersona === 'kaia' || selectedPersona === 'unstable')) {
                            if (forcePersonaChange) {
                                personaSelect.value = 'hypernova';
                                alert("Premium modlara erişiminiz yok. HyperNova'ya geri dönüldü.");
                            }
                        }
                        
                        applyTheme(personaSelect.value, isUserSetTheme ? (document.body.classList.contains('dark-theme') ? 'dark' : 'light') : null);

                    })
                    .catch(error => {
                        console.error('Premium kontrol hatası:', error);
                        // Hata durumunda bile temayı varsayılana ayarla
                        applyTheme(personaSelect.value, isUserSetTheme ? (document.body.classList.contains('dark-theme') ? 'dark' : 'light') : null);
                    });
            }
            
            // Oturum Durumu Arayüzünü Güncelleme
            function updateAuthUI(loggedIn, username, isPremium, premiumUntil) {
                authStatus.innerHTML = '';
                if (loggedIn) {
                    const statusText = `<span>Giriş Yapıldı: <strong>${username}</strong>`;
                    const premiumTag = isPremium ? `<span class="premium-tag">PREMIUM ${premiumUntil ? `(Bitiş: ${premiumUntil.split(' ')[0]})` : ''}</span>` : '';
                    authStatus.innerHTML = `${statusText}${premiumTag}</span><button id="logout-button" onclick="logout()">Çıkış Yap</button>`;
                } else {
                    authStatus.innerHTML = `<span>Giriş yapılmadı.</span><div><button onclick="openAuthModal('login')">Giriş Yap</button><button onclick="openAuthModal('register')">Kayıt Ol</button></div>`;
                }
            }

            // Temayı Uygulama Fonksiyonu (Yeni karakter desteği eklendi)
            function applyTheme(persona, mode = null) {
                // Tüm tema sınıflarını kaldır
                document.body.classList.remove(...THEME_CLASSES);

                let themeClass;
                // Persona'ya göre ana tema sınıfını belirle
                if (persona === 'kaia') {
                    themeClass = 'kaia-theme';
                } else if (persona === 'unstable') {
                    themeClass = 'unstable-theme'; // YENİ
                } else {
                    // Varsayılan HyperNova Teması
                    themeClass = 'default-theme'; 
                }

                // Koyu/Açık mod sınıfını belirle
                let colorMode;
                if (mode) {
                    // Manuel ayar yapıldıysa
                    colorMode = mode;
                } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                    // Sistem tercihini kullan
                    colorMode = 'dark';
                } else {
                    colorMode = 'light';
                }

                if (themeClass === 'default-theme') {
                    document.body.classList.add(colorMode === 'dark' ? 'dark-theme' : 'light-theme');
                } else {
                    document.body.classList.add(themeClass);
                }
                
                // Tema değiştirme butonunun simgesini ayarla
                themeToggle.textContent = colorMode === 'dark' ? '☀️' : '🌙';
            }
            
            // Tema Değiştirme Butonu İşleyicisi
            themeToggle.addEventListener('click', () => {
                isUserSetTheme = true;
                const isDark = document.body.classList.contains('dark-theme') || 
                               (document.body.classList.contains('kaia-theme') && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ||
                               (document.body.classList.contains('unstable-theme') && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);

                // Mevcut durumu tersine çevir
                const newMode = isDark ? 'light' : 'dark';
                
                // Sadece dark/light temasını değiştir, kaia/unstable temasını koru
                let currentPersonaClass = 'default-theme';
                if (document.body.classList.contains('kaia-theme')) {
                    currentPersonaClass = 'kaia-theme';
                } else if (document.body.classList.contains('unstable-theme')) {
                    currentPersonaClass = 'unstable-theme';
                }
                
                document.body.classList.remove(...THEME_CLASSES); // Tüm sınıfları temizle

                if (currentPersonaClass === 'default-theme') {
                    document.body.classList.add(newMode === 'dark' ? 'dark-theme' : 'light-theme');
                } else {
                    // Kaia veya Unstable'da dark/light modunu manuel zorlayamayız, 
                    // bu temaların CSS'i @media ile sistem tercihini kullanıyor. 
                    // Bu yüzden sadece ana temayı tekrar ekleriz.
                    document.body.classList.add(currentPersonaClass);
                }

                // Simgeleri güncelle
                themeToggle.textContent = newMode === 'dark' ? '☀️' : '🌙';
            });
            
            // Persona Değiştirme İşleyicisi (Premium Kontrolü ve Tema Güncellemesi)
            personaSelect.addEventListener('change', () => {
                const selectedPersona = personaSelect.value;
                
                // Kaia veya Unstable seçiliyse ve premium yoksa engelle
                if ((selectedPersona === 'kaia' || selectedPersona === 'unstable') && !isPremium) {
                    alert(`Bu mod (**${selectedPersona.toUpperCase()}**) Premium aboneler için ayrılmıştır. Lütfen giriş yapın ve premium edinin.`);
                    personaSelect.value = 'hypernova';
                }
                
                applyTheme(personaSelect.value, isUserSetTheme ? (document.body.classList.contains('dark-theme') ? 'dark' : 'light') : null);
            });


            // Mesaj Gönderme İşlemi
            async function sendMessage() {
                if (isThinking) return;

                const messageText = userInput.value.trim();
                if (!messageText) return;

                userInput.value = ''; // Giriş alanını temizle
                userInput.style.height = 'auto'; // Yüksekliği sıfırla
                sendButton.disabled = true;
                isThinking = true;
                typingIndicator.classList.add('visible');
                
                // Kullanıcı mesajını ekle
                const userMessage = { role: "user", content: messageText };
                messages.push(userMessage);
                appendMessage(userMessage, "user");
                chatHistory.scrollTop = chatHistory.scrollHeight;

                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            messages: messages.slice(-5), // Son 5 mesajı gönder (context için)
                            persona: personaSelect.value
                        }),
                    });

                    const data = await response.json();

                    if (response.status === 403 && data.force_persona === 'hypernova') {
                        // Premium kısıtlaması gelirse
                        messages.pop(); // Kullanıcı mesajını context'ten sil
                        appendMessage({ content: data.error + " HyperNova'ya geri dönülüyor.", role: "bot" }, "bot");
                        personaSelect.value = 'hypernova';
                        checkPremiumAndApplyTheme(false); // Temayı geri HyperNova'ya çek
                        return;
                    }

                    if (!response.ok) {
                        throw new Error(data.error || 'Bilinmeyen API hatası.');
                    }

                    const botResponse = data.response;
                    const botMessage = { role: "assistant", content: botResponse };
                    messages.push(botMessage);
                    appendMessage(botMessage, "bot");

                } catch (error) {
                    console.error('Sohbet hatası:', error);
                    const errorMessage = { role: "bot", content: "Üzgünüm, iletişim kesildi veya bir hata oluştu: " + error.message };
                    appendMessage(errorMessage, "error");
                    // Hata mesajını context'e eklemiyoruz
                } finally {
                    isThinking = false;
                    typingIndicator.classList.remove('visible');
                    sendButton.disabled = false;
                    chatHistory.scrollTop = chatHistory.scrollHeight;
                }
            }

            // DOM'a Mesaj Ekleme
            function appendMessage(message, type) {
                const messageDiv = document.createElement('div');
                messageDiv.classList.add(type === "user" ? "user-message" : "bot-message");
                
                if (type === "error") {
                    messageDiv.classList.add('error-message');
                    messageDiv.style.backgroundColor = '#fecaca';
                    messageDiv.style.color = '#991b1b';
                    messageDiv.textContent = message.content;
                } else {
                    // Markdown'ı HTML'e çevirme (basit bir örnek)
                    let htmlContent = message.content;
                    // Kalın metin
                    htmlContent = htmlContent.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                    // Satır sonları
                    htmlContent = htmlContent.replace(/\n/g, '<br>');

                    messageDiv.innerHTML = htmlContent;
                }
                
                chatHistory.appendChild(messageDiv);
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }

            // ... (Kayıt/Giriş/Çıkış modal ve submit fonksiyonları aynı kalır) ...
            
            // Sayfa Yüklendiğinde
            document.addEventListener('DOMContentLoaded', () => {
                checkPremiumAndApplyTheme(false);
                userInput.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                    }
                });
                sendButton.addEventListener('click', sendMessage);
                
                clearButton.addEventListener('click', () => {
                    messages = []; // Context'i temizle
                    chatHistory.innerHTML = '<div class="bot-message">Sohbet sıfırlandı! Yeni bir maceraya hazır mısın? 🚀</div>'; // Geçici ilk mesajı geri koy
                });
            });

            // --- Basit Modal ve Auth Fonksiyonları (Çok Detaylı Olmadığı İçin Aynı Kaldı) ---

            function openAuthModal(mode) {
                currentAuthMode = mode;
                document.getElementById('modal-title').textContent = mode === 'login' ? 'Giriş Yap' : 'Kayıt Ol';
                document.getElementById('modal-submit-button').textContent = mode === 'login' ? 'Giriş Yap' : 'Kayıt Ol';
                document.getElementById('modal-message').textContent = mode === 'login' ? 'HyperNova'nın Premium özelliklerine erişmek için giriş yapın.' : 'Bir hesap oluşturun ve HyperNova'nın gücünü deneyimleyin.';
                document.getElementById('modal-error').textContent = '';
                document.getElementById('auth-modal').style.display = 'block';
            }

            async function handleAuthSubmit() {
                const username = document.getElementById('auth-username').value.trim();
                const password = document.getElementById('auth-password').value;
                const errorElement = document.getElementById('modal-error');
                errorElement.textContent = '';

                if (!username || !password) {
                    errorElement.textContent = "Kullanıcı adı ve şifre boş bırakılamaz.";
                    return;
                }

                try {
                    const endpoint = currentAuthMode === 'login' ? '/login' : '/register';
                    const response = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    const data = await response.json();

                    if (!response.ok) {
                        errorElement.textContent = data.error || 'İşlem başarısız oldu.';
                        return;
                    }

                    alert(data.message);
                    document.getElementById('auth-modal').style.display = 'none';
                    document.getElementById('auth-username').value = '';
                    document.getElementById('auth-password').value = '';

                    if (currentAuthMode === 'login') {
                        // Giriş başarılıysa premium durumunu tekrar kontrol et ve UI'ı güncelle
                        checkPremiumAndApplyTheme(false); 
                    } else {
                         // Kayıt başarılıysa, giriş yapması için modalı tekrar aç
                         openAuthModal('login');
                    }

                } catch (error) {
                    errorElement.textContent = 'Bağlantı hatası: ' + error.message;
                }
            }

            async function logout() {
                try {
                    const response = await fetch('/logout', { method: 'POST' });
                    const data = await response.json();
                    if (response.ok) {
                        alert(data.message);
                        checkPremiumAndApplyTheme(true); // Persona'yı HyperNova'ya zorla
                    } else {
                        alert(data.message || 'Çıkış yapılamadı.');
                    }
                } catch (error) {
                    alert('Çıkış işlemi sırasında bağlantı hatası.');
                }
            }


        </script>
    </body>
    </html>
    """
    return html_template

if __name__ == '__main__':
    # Geliştirme kolaylığı için başlangıçta test kullanıcıları ekle
    # (Bu kısım gerçek uygulamada kaldırılmalı veya veritabanından yüklenmelidir)
    if not USER_DB:
        USER_DB["testuser"] = {
            'username': "testuser",
            'password': "123",
            'premium_until': datetime.now() - timedelta(days=1) # Premium bitmiş
        }
        USER_DB["premium_test"] = {
            'username': "premium_test",
            'password': "456",
            'premium_until': datetime.now() + timedelta(days=30) # Premium aktif
        }
    
    # app.run(debug=True, port=8080)
    # Basit bir sunucu için
    from waitress import serve
    print("Web sunucusu başlatılıyor...")
    serve(app, host='0.0.0.0', port=5000)
