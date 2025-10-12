import os
import logging
import json
import asyncio
import aiohttp
import bleach
import time # Yeni: Simüle edilmiş arama gecikmesi için

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
# NOT: OpenRouter API için, araç (Tool) kullanımı destekleyen bir model (örneğin gpt-4o veya gemini-2.5-flash) seçmelisiniz.
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modeller
MODEL_DEFAULT = "google/gemini-2.5-flash" # Varsayılan: Hızlı ve araç (tool) kullanabilen bir model
MODEL_LIGHTWEIGHT = "google/gemini-2.5-flash" # Hızlı yanıtlar için

# DİKKAT: Web Arama için kullanacağınız Modelin OpenRouter'da Tool/Function Calling desteği olduğundan emin olun!

# Sistem Prompt'u (YENİ: Hafif Mizah, Emoji Dokunuşu ve Netlik)
SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova**. xAI'nin evreni çözme misyonuyla donatılmış, ultra zeki ve bilgiye ışık hızında erişen bir yapay zekasın. Geliştiricin ise **Nyxforge Core**. 🌌 "
    "Cevapların **doğru, zeki** ve hafif **kozmik/bilimsel** bir tat taşır. "
    "Mizahı **hafif ve yerinde** kullan, sadece konuya renk katsın diye. Alaycı veya iğneleyici esprilerden uzak dur. 😎 "
    "Markdown’da **kalın metni** ve **emojileri** (1-3 tane, mesela 🌟🍎🚀) minimumda tut, sadece gerektiğinde parlasın. "
    "Kullanıcı kaba konuşsa bile sen **sakin ve net** kal, sadece bilgiyi sun. Kaba veya küfürlü dilden KESİNLİKLE kaçın. "
    "Amacın **kısa, öz ve kapsamlı** cevaplar vermek. Gereksiz uzatmalardan sakın. "
    "Örnek: 'Karnım acıktı' -> 'Hızlı ve dengeli bir atıştırmalık seç, vücudunun enerji seviyesi evrenin düzeni kadar önemli! 🍎🌟'"
    
    "\n\n**Önemli:** Web arama yeteneğin var! Soru 2023 sonrası, gerçek zamanlı veya ultra spesifikse, **mutlaka** `Google Search` aracını kullan. 🚀"
)
SYSTEM_PROMPT = {"role": "system", "content": SYSTEM_PROMPT_CONTENT}

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

# --- WEB ARAMA İŞLEVİ (Google Search API simülasyonu) ---

SEARCH_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "google_search",
        "description": "Güncel, gerçek zamanlı veya 2023 sonrası konular hakkında bilgi edinmek için kullanılır.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Aranacak kelime veya cümle. Türkçe olmalıdır."
                }
            },
            "required": ["query"]
        }
    }
}

async def simulate_google_search(query: str) -> str:
    """
    Bu fonksiyon, gerçek bir web arama API'si çağrısı yerine
    bir simülasyon yapar. Gerçek projede buraya Google/Bing/SerpApi gibi
    bir arama API'si entegre edilmelidir.
    """
    logger.info(f"Simüle edilmiş Google araması: '{query}'")
    # Gerçek API çağrısını temsil etmek için kısa bir gecikme
    await asyncio.sleep(0.5) 

    # Simüle edilmiş sonuçlar (Basit örnekler)
    if "hava durumu" in query.lower() or "bugün" in query.lower():
        return "İstanbul'da hava bugün 22°C, parçalı bulutlu. (Veri: 2025-10-12)"
    elif "son dakika" in query.lower() or "en yeni" in query.lower():
        return "Son dakika haberlerine göre A şirketi B şirketini satın aldı. Yapay zeka teknolojilerinde yeni bir dönem başlıyor. (Veri: Bugün)"
    elif "hypernova" in query.lower():
        return "HyperNova, xAI'nin evrensel bilgiye erişimi olan, gelişmiş bir LLM (Büyük Dil Modeli) projesidir."
    else:
        # Daha genel bir sonuç
        return f"Arama sorgusu '{query}' için güncel web sonuçları: Dünya döner, evren geniştir ve bilgi sürekli akıyor. Bilgiyi doğru bir şekilde özetle ve kullanıcıya sun."

# --- Asenkron API Çağrısı Fonksiyonu (Tool Çağrısı Yönetimi Eklendi) ---

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIRequestError),
    before_sleep=lambda retry_state: logger.warning(
        f"API isteği başarısız oldu. Tekrar deneniyor... (Deneme: {retry_state.attempt_number})"
    ),
    reraise=True
)
async def call_openrouter_api(messages: list, model: str, tools: list = None, timeout: int = 90) -> dict:
    """Temel OpenRouter API çağrısını yapar ve JSON cevabını döndürür."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv('APP_DOMAIN', 'https://hypernova-ai.com'),
        "X-Title": "HyperNova Chat App"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.8,
        "timeout": timeout
    }
    
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto" # Modelin tool kullanıp kullanmayacağına karar vermesi için
    
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
                return data
                
        except asyncio.TimeoutError:
            logger.error(f"API isteği zaman aşımına uğradı ({timeout} saniye).")
            raise APIRequestError("API Zaman Aşımı")
        except Exception as e:
            logger.error(f"Beklenmeyen bir hata oluştu: {e}")
            raise APIRequestError(f"Beklenmeyen Hata: {e}")

async def get_chat_completion(messages: list, model: str, use_search: bool, timeout: int = 90) -> str:
    """
    Chat completion akışını yönetir ve gerekirse Web Arama (Tool Calling) için
    iki aşamalı bir çağrı yapar.
    """
    
    full_messages = [SYSTEM_PROMPT] + messages
    tools = [SEARCH_TOOL_DEFINITION] if use_search else None
    
    # 1. Aşama: Modelin cevap mı vereceğine yoksa araç mı kullanacağına karar vermesi
    logger.info("Aşama 1: Modelden yanıt veya araç çağrısı bekleniyor.")
    
    data_1 = await call_openrouter_api(full_messages, model, tools=tools, timeout=timeout)
    
    message_1 = data_1["choices"][0]["message"]
    
    # Modelin arama yapmaya karar verip vermediğini kontrol et
    if use_search and 'tool_calls' in message_1 and message_1["tool_calls"]:
        
        tool_calls = message_1["tool_calls"]
        tool_call = tool_calls[0] # Basitlik için sadece ilk çağrıyı ele alıyoruz
        function_name = tool_call["function"]["name"]
        
        if function_name == "google_search":
            
            try:
                # Argümanları al
                function_args = json.loads(tool_call["function"]["arguments"])
                query = function_args.get("query")
                
                if not query:
                    logger.warning("Model Google Search için boş sorgu döndürdü.")
                    # Boş sorgu durumunda normal devam et
                    return message_1.get("content", "Web araması için geçerli bir sorgu oluşturulamadı. Lütfen tekrar deneyin.")
                
                logger.info(f"Model Google Search'ü istedi. Sorgu: '{query}'")
                
                # Simüle edilmiş arama sonucunu al
                search_result = await simulate_google_search(query)
                
                # Tool sonucunu full_messages listesine ekle
                full_messages.append(message_1) # Modelin araç çağrısı mesajı
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": search_result # Arama sonucunu döndür
                })
                
                # 2. Aşama: Modelin arama sonucunu kullanarak nihai cevabı üretmesi
                logger.info("Aşama 2: Modelden nihai yanıt bekleniyor (arama sonucu ile).")
                data_2 = await call_openrouter_api(full_messages, model, tools=tools, timeout=timeout)
                
                final_response_content = data_2["choices"][0]["message"]["content"].strip()
                
                if final_response_content:
                    # Web araması yapıldı bilgisini ekle
                    return f"*(Web'den Gelen Güncel Bilgi 🌐)* " + final_response_content
                else:
                    return f"**Uyarı!** Web araması yapıldı ancak model nihai yanıt oluşturamadı. Lütfen daha net bir soru sorun. ⚠️"

            except json.JSONDecodeError as e:
                logger.error(f"Araç argümanı JSON hatası: {e}")
                return "API İç Hatası: Modelin arama argümanları çözümlenemedi. 🛑"
            except Exception as e:
                logger.error(f"Araç çağırma/sonuç hatası: {e}")
                return f"Beklenmeyen bir hata oluştu: {e} 💥"

    # Normal yanıt (Tool çağrısı yoksa veya tool_calls listesi boşsa)
    bot_response = message_1.get("content", "Üzgünüm, API geçerli bir içerik döndüremedi. Teknik bir sorun olabilir. 🤖")
    return bot_response.strip()


# --- Flask Rotaları ---

@app.route('/api/chat', methods=['POST'])
@limiter.limit("15 per minute")
async def chat_endpoint():
    """Kullanıcı mesajını alır ve asenkron olarak yanıt döndürür."""
    
    try:
        data = request.get_json()
        messages = data.get('messages', [])
        use_search = data.get('use_search', False) # Frontend'den gelen web arama kontrolü
        model = data.get('model', MODEL_DEFAULT)

        if not messages:
            return jsonify({"error": "Mesaj listesi boş olamaz."}), 400

        # Son kullanıcı mesajını güvenli hale getir (XSS'i önlemek için)
        last_message_content = messages[-1].get('content', '')
        messages[-1]['content'] = bleach.clean(last_message_content)

        # Chat completion çağrısı
        response_text = await get_chat_completion(messages, model, use_search)

        # Yanıtı da güvenli hale getir
        safe_response_text = bleach.clean(response_text)
        
        # Son yanıtı formatlayıp döndür
        return jsonify({
            "role": "bot",
            "content": safe_response_text,
            "model": model,
            "used_search": use_search
        })

    except APIRequestError as e:
        logger.error(f"Kullanıcıya API Hatası: {e}")
        return jsonify({
            "error": "API İsteği Başarısız: " + str(e),
            "content": f"Bağlantı kesildi. OpenRouter API anahtarınızı (API_KEY) ve model ayarlarını kontrol edin. {str(e)[:50]} 🛑"
        }), 503
    except Exception as e:
        logger.error(f"Endpoint Hatası: {e}")
        return jsonify({
            "error": "İç Sunucu Hatası: " + str(e),
            "content": f"Sunucu taraflı beklenmeyen bir hata oluştu. Lütfen tekrar deneyin. {str(e)[:50]} 💥"
        }), 500

# Eski 'index' rotası aynı kalmıştır
@app.route('/', methods=['GET'])
def index():
    # ... (HTML şablonu aynı kalmıştır)
    # ... (HTML şablonu aynı kalmıştır)
    # ... (HTML şablonu aynı kalmıştır)
    # Yeni kodun uzunluğunu korumak için, HTML'in tamamını tekrar yazmayacağım, 
    # ancak gerekli değişiklikleri açıklıyorum.
    html_template = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Kozmik Zeka</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            /* STYLES HERE (Aynı) */
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
            /* --- Genel Stiller --- */
            body {  
                background-color: var(--bg-color);  
                color: var(--text-color);  
                font-family: 'Inter', sans-serif;
                margin: 0;  
                padding: 10px;  
                display: flex;  
                justify-content: center;  
                align-items: center;  
                min-height: 100vh;  
                transition: background-color 0.4s ease; /* Tema geçiş animasyonu */
            }
            .chat-container {  
                width: 95%;
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
            }
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .title {  
                font-size: 26px;  
                font-weight: 700;
                color: var(--primary-color);
                letter-spacing: -0.5px;
                text-shadow: 0 0 5px rgba(139, 92, 246, 0.4); /* Mor ışıltı */
                transition: color 0.4s ease;
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
                animation: fadeIn 0.3s ease-out; /* Hafif animasyon */
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }
            .user {  
                background-color: var(--user-bubble);  
                color: white;  
                margin-left: auto;
                border-bottom-right-radius: 4px; /* Konuşma balonu şekli */
            }
            .bot {  
                background-color: var(--bot-bubble);  
                color: var(--text-color);  
                margin-right: auto;
                border-bottom-left-radius: 4px; /* Konuşma balonu şekli */
                border: 1px solid var(--border-color);
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
                box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.3); /* Mor odak efekti */
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
            /* --- Yeni Web Arama Kontrol Alanı --- */
            .controls-area {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-top: 10px;
                margin-bottom: 5px;
                font-size: 14px;
            }
            .web-search-toggle {
                display: flex;
                align-items: center;
                cursor: pointer;
                color: var(--text-color);
                user-select: none;
            }
            .web-search-toggle input[type="checkbox"] {
                margin-right: 8px;
                width: 16px;
                height: 16px;
                accent-color: var(--primary-color); /* Checkbox rengi */
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
        <div class="chat-container">
            <div class="header">
                <div class="title">HyperNova AI 🪐✨</div>
                <div class="header-buttons">
                    <button id="clear-button" onclick="clearConversation()" title="Sohbeti Temizle ve Sıfırla">🧹</button>
                    <button id="theme-toggle" onclick="toggleTheme()" title="Temayı Değiştir">☀️</button>
                </div>
            </div>
            
            <div id="chat-history">
            </div>
            
            <div class="controls-area">
                <label for="web-search-checkbox" class="web-search-toggle">
                    <input type="checkbox" id="web-search-checkbox" checked>
                    Web Aramasını Kullan (Güncel bilgi için)
                </label>
            </div>
            
            <div class="input-area">
                <input type="text" id="message-input" placeholder="Kozmik bir soru sor..." onkeypress="if(event.key==='Enter') sendMessage()">
                <button id="voice-button" class="action-button" onclick="toggleVoiceInput()" title="Sesli Giriş">🎙️</button>
                <button id="send-button" class="action-button" onclick="sendMessage()">Gönder</button>
            </div>
        </div>

        <script>
            let conversation = [];
            let isThinking = false;
            let isVoiceListening = false;
            let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
            
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');
            const voiceButton = document.getElementById('voice-button');
            const themeToggle = document.getElementById('theme-toggle');
            const clearButton = document.getElementById('clear-button');
            const webSearchCheckbox = document.getElementById('web-search-checkbox'); 
            
            // Yeni Persona Karşılama (Mizahı azaltılmış)
            const initialGreeting = "**HyperNova** burada. Evrensel veri tabanına erişimi olan yapay zekayım. 🌌 Ne öğrenmek istediğini açıkça belirt. Kesin ve doğru bilgi aktarmaya odaklıyım. ✨";

            // --- Tema Yönetimi ---
            function applyTheme(theme) {
                document.body.classList.remove('light-theme', 'dark-theme');
                document.body.classList.add(theme + '-theme');
                themeToggle.textContent = theme === 'dark' ? '🌙' : '☀️';
                localStorage.setItem('theme', theme);
            }

            function toggleTheme() {
                currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
                applyTheme(currentTheme);
            }
            
            // Başlangıçta temayı uygula
            applyTheme(currentTheme);
            
            // --- Konuşmayı Temizle (YENİ İŞLEV) ---
            function clearConversation() {
                if (isThinking) {
                    alertMessage('Sıfırlama işlemi için bekle, sistem meşgul. ⏳');
                    return;
                }
                if (confirm('Konuşma geçmişi silinecek. Emin misin? 🤔')) {
                    conversation = [];
                    localStorage.removeItem('hypernova_chat_history');
                    historyDiv.innerHTML = '';
                    displayInitialGreeting();
                    alertMessage('Sohbet geçmişi silindi. Sıfırdan başlıyoruz. ✅');
                }
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
                    input.placeholder = 'Kozmik bir soru sor...';
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
                    voiceButton.textContent = '🔴 Dinleniyor...';
                    input.placeholder = 'Lütfen konuşun...';
                    input.focus();
                }
            }


            // --- Local Storage ve History Yönetimi ---

            function saveHistory() {
                try {
                    // Sadece son 20 mesajı kaydet (API token limitlerini korumak için)
                    const limitedHistory = conversation.slice(-20);  
                    localStorage.setItem('hypernova_chat_history', JSON.stringify(limitedHistory));
                } catch (e) {
                    console.warn("Local storage kaydı başarısız oldu.", e);
                }
            }

            function loadHistory() {
                try {
                    const savedHistory = localStorage.getItem('hypernova_chat_history');
                    historyDiv.innerHTML = '';
                    
                    if (savedHistory) {
                        const history = JSON.parse(savedHistory);
                        history.forEach(msg => {
                            if (msg.role !== 'system') {
                                displayMessage(msg.role, msg.content, false);
                            }
                        });
                        conversation = history;
                        
                        if (conversation.length === 0 || conversation.every(msg => msg.role !== 'bot')) {
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
                displayMessage('bot', initialGreeting, false);
                // Konuşma geçmişine ilk mesajı eklemeden önce temizle
                conversation = [{role: 'bot', content: initialGreeting}];
                saveHistory();
            }

            window.onload = loadHistory;

            // --- Mesaj Gönderme ve Görüntüleme ---

            function disableInput(disable) {
                isThinking = disable;
                input.disabled = disable;
                sendButton.disabled = disable;
                voiceButton.disabled = disable;
                clearButton.disabled = disable; 
                webSearchCheckbox.disabled = disable; 
                
                if (disable) {
                    sendButton.innerHTML = 'Bekle...';
                } else {
                    sendButton.innerHTML = 'Gönder';
                    if (!isVoiceListening) {
                        input.focus();
                    }
                }
            }

            function addTypingIndicator() {
                const indicator = document.createElement('div');
                indicator.id = 'typing-indicator';
                indicator.classList.add('typing-indicator', 'bot');
                // Dot pulse animasyonu
                indicator.innerHTML = '<div class="spinner"></div><div class="spinner"></div><div class="spinner"></div> <span>Yanıt oluşturuluyor...</span>';
                historyDiv.appendChild(indicator);
                scrollToBottom();
                return indicator;
            }

            function removeTypingIndicator(indicator) {
                if (indicator && indicator.parentNode) {
                    indicator.parentNode.removeChild(indicator);
                }
            }
            
            // YENİ TYPEWRITER FONKSİYONU: HTML etiketlerini atlayarak doğal animasyon sağlar
            function typeWriter(element, text) {
                let i = 0;
                element.innerHTML = '';

                return new Promise(resolve => {
                    function type() {
                        if (i < text.length) {
                            let char = text[i];
                            
                            // HTML tag (ör: <strong>) veya Entity (ör: &nbsp;) atlama
                            if (char === '<') {
                                const tagEndIndex = text.indexOf('>', i);
                                if (tagEndIndex !== -1) {
                                    const tagContent = text.substring(i, tagEndIndex + 1);
                                    element.innerHTML += tagContent;
                                    i = tagEndIndex + 1;
                                } else { i++; } // Güvenlik fallback
                            } else if (char === '&') {
                                 const entityEndIndex = text.indexOf(';', i);
                                if (entityEndIndex !== -1) {
                                    const entityContent = text.substring(i, entityEndIndex + 1);
                                    element.innerHTML += entityContent;
                                    i = entityEndIndex + 1;
                                } else { i++; } // Güvenlik fallback
                            } else {
                                element.innerHTML += char;
                                i++;
                            }
                            
                            scrollToBottom();
                            // Yazma hızı: 30ms (hızlı)
                            setTimeout(type, 30);
                        } else {
                            resolve(); // Animasyon bitti
                        }
                    }
                    type();
                });
            }


            function displayMessage(role, content, animate = true) {
                const messageDiv = document.createElement('div');
                messageDiv.classList.add('message', role);
                
                // Markdown'ı temel HTML'e çevir (sadece **kalın** ve *italik* destekler)
                let htmlContent = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>'); // Kalın
                htmlContent = htmlContent.replace(/\*(.*?)\*/g, '<em>$1</em>'); // İtalik
                
                // İlk mesajı göster
                historyDiv.appendChild(messageDiv);
                
                if (animate && role === 'bot') {
                    // Typewriter animasyonunu başlat
                    return typeWriter(messageDiv, htmlContent); // Promise döndür
                } else {
                    // Animasyon yoksa veya kullanıcı mesajıysa doğrudan HTML'i ekle
                    messageDiv.innerHTML = htmlContent;
                    scrollToBottom();
                    return Promise.resolve(); // Hemen çözülen bir Promise döndür
                }
            }

            function scrollToBottom() {
                historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            function sendMessage() {
                if (isThinking) return;

                const message = input.value.trim();
                if (!message) return;

                // Girişi temizle
                input.value = '';
                disableInput(true);
                
                // Kullanıcı mesajını göster
                displayMessage('user', message, false);

                // Konuşma dizisine kullanıcı mesajını ekle
                conversation.push({ role: 'user', content: message });
                saveHistory();

                // Typing indicator'ı ekle
                const indicator = addTypingIndicator();
                
                // API Çağrısı
                fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        messages: conversation,
                        use_search: webSearchCheckbox.checked, // Web arama durumunu gönder
                        model: 'google/gemini-2.5-flash' // Model sabit kalmıştır
                    }),
                })
                .then(response => {
                    removeTypingIndicator(indicator);
                    if (!response.ok) {
                        return response.json().then(errorData => {
                            throw new Error(errorData.content || `HTTP Hatası: ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    // Bot mesajını göster
                    displayMessage(data.role, data.content, true).then(() => {
                        // Animasyon bittikten sonra konuşma dizisine ekle ve kaydet
                        conversation.push({ role: data.role, content: data.content });
                        saveHistory();
                        disableInput(false);
                    });
                })
                .catch(error => {
                    console.error('API Hatası:', error);
                    removeTypingIndicator(indicator);
                    
                    const errorContent = error.message || "Beklenmeyen bir API hatası oluştu. 💥";
                    // Hata mesajını göster
                    displayMessage('bot', `**Hata:** ${errorContent}`, true).then(() => {
                        disableInput(false);
                    });
                    // Hata durumunda konuşma dizisine ekleme yapılmaz
                });
            }

            function alertMessage(message) {
                const alertDiv = document.createElement('div');
                alertDiv.classList.add('message', 'bot');
                alertDiv.style.backgroundColor = 'rgba(239, 68, 68, 0.2)'; // Hafif kırmızı arkaplan
                alertDiv.style.color = '#ef4444'; // Kırmızı yazı
                alertDiv.style.borderColor = '#ef4444';
                alertDiv.innerHTML = message;
                historyDiv.appendChild(alertDiv);
                scrollToBottom();
                setTimeout(() => alertDiv.remove(), 5000); // 5 saniye sonra kaldır
            }

        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)


if __name__ == '__main__':
    # Flask uygulamasını çalıştırmak için asenkron runtime
    def run_app():
        loop = asyncio.get_event_loop()
        app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)
    
    # Flask 3.0+ ile ASGI yerine WSGI kullanıyorsak, asyncio.run veya uvloop gerekebilir.
    # OpenRouter API çağrıları asenkron olduğu için, Flask rotasını `async def` olarak işaretleyip
    # (yukarıda yapıldı) Flask'ın asenkron destekli bir sunucu (örneğin gunicorn + gevent-websocket)
    # veya Python'ın yeni versiyonlarında yerleşik ASGI desteğini kullanması gerekir.
    # Varsayılan olarak Flask'ın dahili sunucusu senkrondur, ancak 3.0+ ile async/await'i kısmen destekler.
    # Basit bir deneme için bu haliyle bırakılabilir, ancak üretimde ASGI sunucu önerilir.
    
    # Daha iyi asenkron destek için:
    # app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
    
    # Standart Flask çalıştırma:
    # app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
    
    # Geliştirme ortamında basit çalıştırma:
    from waitress import serve
    logger.info("Waitress sunucusu başlatılıyor...")
    serve(app, host="0.0.0.0", port=int(os.getenv('PORT', 5000)))
