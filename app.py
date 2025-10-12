import os
import logging
import json
import asyncio
import aiohttp
import bleach

from flask import Flask, request, jsonify, render_template_string
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

# --- KARAKTER PROMPTLARI ---

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
    "Örnek: 'Bugün çok yoruldum' -> 'Ahhh, canım benim! 🥺 Bir çay yap ve biraz dinlen. Seni böyle görmek beni üzüyor! 💖'"
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


# --- Flask Rotaları ---

@app.route('/chat', methods=['POST'])
@limiter.limit("15 per minute")
async def chat_endpoint():
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        # YENİ: Hangi persona'nın seçildiğini al
        persona = data.get('persona', DEFAULT_PERSONA) 

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
            
            /* ... (Kaldırılan CSS kodları yerine sadece farklı olanları tutalım) ... */
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px; /* Kişi seçimi için boşluk bırakıldı */
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
                content: "✨ Reklamsız Deneyim ve Özel Kaia Temaları için Premium'a Geç! ✨";
            }
            #ad-banner:hover {
                background-color: rgba(255, 200, 0, 0.3);
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
            
            <select id="persona-select" onchange="changePersona()">
                <option value="hypernova">HyperNova (Standart) 🪐</option>
                <option value="kaia">Kaia (Anime Kızı) 💖</option>
            </select>

            <div id="chat-history">
            </div>
            
            <div id="ad-banner" onclick="alert('Premium Abone Olma Sayfasına Yönlendiriliyorsunuz!')">
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

            // --- Tema Yönetimi ---
            function applyTheme(theme) {
                document.body.classList.remove('light-theme', 'dark-theme', 'kaia-theme');
                if (currentPersona === 'kaia') {
                    document.body.classList.add('kaia-theme');
                    // Kaia'nın kendi renkleri olduğu için light/dark modunu zorlamaya gerek yok
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
            
            // --- Persona Yönetimi (YENİ) ---
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
            }

            function changePersona() {
                const newPersona = personaSelect.value;
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


            // --- Konuşmayı Temizle ---
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

            // --- Local Storage ve History Yönetimi ---
            function saveHistory() {
                try {
                    const limitedHistory = conversation.slice(-20);  
                    localStorage.setItem('hypernova_chat_history_' + currentPersona, JSON.stringify(limitedHistory));
                } catch (e) {
                    console.warn("Local storage kaydı başarısız oldu.", e);
                }
            }

            function loadHistory() {
                updateUIForPersona(); // UI'ı doğru persona'ya göre ayarla

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
            }
            
            function displayInitialGreeting() {
                const greetingText = GREETINGS[currentPersona].text;
                displayMessage('bot', greetingText, false);
                conversation = [{role: 'bot', content: greetingText}];
                saveHistory();
            }

            window.onload = loadHistory;

            // --- Voice Input ve Diğer İşlevler (Değişmedi) ---
            
            function displayMessage(role, content, save=true) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                // Markdown desteği: Basit **koyu metin** için
                let htmlContent = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                messageDiv.innerHTML = htmlContent;
                historyDiv.appendChild(messageDiv);
                
                if (save) {
                    conversation.push({role: role, content: content});
                    saveHistory();
                }
                scrollToBottom();
            }
            
            function scrollToBottom() {
                historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            function setThinking(isTyping) {
                isThinking = isTyping;
                sendButton.disabled = isTyping;
                input.disabled = isTyping;
                voiceButton.disabled = isTyping;
                clearButton.disabled = isTyping;

                let typingIndicator = document.getElementById('typing-indicator');
                if (isTyping) {
                    if (!typingIndicator) {
                        typingIndicator = document.createElement('div');
                        typingIndicator.id = 'typing-indicator';
                        typingIndicator.className = 'typing-indicator';
                        typingIndicator.innerHTML = `
                            <span>${currentPersona === 'kaia' ? 'Kaia yazıyor...' : 'HyperNova düşünüyor...'}</span>
                            <div class="spinner"></div>
                            <div class="spinner"></div>
                            <div class="spinner"></div>
                        `;
                        historyDiv.appendChild(typingIndicator);
                        scrollToBottom();
                    }
                } else {
                    if (typingIndicator) {
                        typingIndicator.remove();
                    }
                }
            }

            async function sendMessage() {
                const userMessage = input.value.trim();
                if (userMessage === "" || isThinking) return;

                // Kullanıcı mesajını göster
                displayMessage('user', userMessage);
                input.value = ''; // Input'u temizle
                setThinking(true);

                // API çağrısı için son 10 mesajı al (System prompt hariç)
                const apiMessages = conversation.slice(-10).map(msg => ({
                    role: msg.role, 
                    content: msg.content
                }));

                try {
                    const response = await fetch('/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            messages: apiMessages, 
                            persona: currentPersona // Seçilen persona'yı gönder
                        })
                    });

                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || `HTTP hata kodu: ${response.status}`);
                    }

                    const data = await response.json();
                    displayMessage('bot', data.response);

                } catch (error) {
                    console.error('Sohbet hatası:', error);
                    let errorMessage = 'Bağlantı Hatası: Sunucuya ulaşılamıyor. 🌐';
                    if (error.message.includes('API Key Hatası')) {
                        errorMessage = 'API Anahtarı Ayarlanmamış! Lütfen backend kodunuzdaki `API_KEY` değişkenini güncelleyin.';
                    } else if (error.message.includes('API Zaman Aşımı')) {
                        errorMessage = 'İşlem zaman aşımına uğradı. Tekrar dene. ⏳';
                    } else if (error.message.includes('Limit')) {
                        errorMessage = 'İstek limitini aştın! Bir saat beklemen gerekiyor. 🔒';
                    } else if (error.message.includes('OpenRouter API Hatası')) {
                         errorMessage = `OpenRouter Hatası: ${error.message}`;
                    }
                    displayMessage('bot', `**HATA!** ${errorMessage}`, false);
                } finally {
                    setThinking(false);
                }
            }
            
            function alertMessage(msg) {
                // Basit bir uyarı mesajı (isteğe bağlı olarak geliştirilebilir)
                console.log(msg); 
                // alert(msg); // Kullanıcı deneyimini bozmaması için yorum satırı yapıldı
            }

            // --- Voice Input (Web Speech API) ---
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if (SpeechRecognition) {
                recognition = new SpeechRecognition();
                recognition.lang = 'tr-TR';
                recognition.interimResults = false;

                recognition.onresult = (event) => {
                    const speechResult = event.results[0][0].transcript;
                    input.value = speechResult;
                    toggleVoiceInput();
                    sendMessage();
                };

                recognition.onend = () => {
                    if (isVoiceListening) {
                        recognition.start();
                    }
                    voiceButton.classList.remove('listening');
                    voiceButton.textContent = '🎙️';
                    input.placeholder = GREETINGS[currentPersona].placeholder;
                };

                recognition.onerror = (event) => {
                    console.error('Sesli tanıma hatası:', event.error);
                    alertMessage('Sesli giriş başarısız. Mikrofon izni kontrol et.');
                    isVoiceListening = false;
                    voiceButton.classList.remove('listening');
                    voiceButton.textContent = '🎙️';
                };
            } else {
                voiceButton.style.display = 'none';
            }

            function toggleVoiceInput() {
                if (isThinking) {
                    alertMessage('Sistem meşgul, lütfen cevap gelene kadar bekle. ⏳');
                    return;
                }
                if (isVoiceListening) {
                    isVoiceListening = false;
                    recognition.stop();
                } else {
                    isVoiceListening = true;
                    recognition.start();
                    voiceButton.classList.add('listening');
                    voiceButton.textContent = '🔴 Dinliyorum...';
                    input.placeholder = 'Konuş...';
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)

if __name__ == '__main__':
    # Flask uygulamasını çalıştırmak için gerekli
    if os.name == 'nt': # Windows için
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    # Güvenlik için sadece localhost'ta çalıştırırken debug=True kullanın
    app.run(host='0.0.0.0', port=5000, debug=True)
