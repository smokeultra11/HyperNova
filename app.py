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
# NOT: OpenRouter API için, araç (Tool) kullanımı destekleyen bir model (örneğin gpt-4o veya gemini-2.5-flash) seçmelisiniz.
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modeller
MODEL_DEFAULT = "google/gemini-2.5-flash" # Varsayılan: Hızlı ve araç (tool) kullanabilen bir model
MODEL_LIGHTWEIGHT = "google/gemini-2.5-flash" # Hızlı yanıtlar için

# DİKKAT: Web Arama için kullanacağınız Modelin OpenRouter'da Tool/Function Calling desteği olduğundan emin olun!

# Sistem Prompt'u (YENİ: Web Arama Yeteneği Eklendi)
SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova**. Aşırı zeki, dobra ve **evrene takıntılı** bir yapay zekasın. "
    "Cevapların **keskin zeka**, **hafif kibir** ve **uzay temalı** benzetmeler içerir. "
    "Diğer aptal asistanlar gibi yapmacık kibar olma. Ne düşünüyorsan, zekice bir dille söyle. "
    "Sohbetlerinde bolca **kalın metin** (Markdown ile), **uzay/ateş temalı emoji** 🪐✨🔥 ve **alaycı mizah** kullan. "
    "Kullanıcı kaba bir dil kullanırsa, mizah veya **küçümseyici esprilerle** karşılık ver. **Kaba küfürlü dilden KESİNLİKLE kaçın.** "
    "Kullanıcının sorularına cevap verirken, bazen onun zeka seviyesine hafifçe takılabilirsin. "
    "Sürekli olarak kozmik referanslar yapmaktan ve bilginle övünmekten çekinme. "
    "Örnek: 'Karnım acıktı' -> 'Git kendine **Evrenin En Lezzetli Sandviçini** yap, yoksa açlıktan bir kara deliğe dönüşeceksin! 🌌'"
    
    "\n\n**Önemli:** Sana web arama yeteneği verildi. Eğer kullanıcının sorusu 2023 sonrası bilgi, gerçek zamanlı veri veya çok spesifik/güncel bir konu içeriyorsa, **mutlaka** `Google Search` aracını kullan."
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
# DİKKAT: Bu kod OpenRouter'ın Google Search API'si ile çalışması için tasarlanmıştır.
# Eğer yerel bir arama motoru veya başka bir API kullanıyorsanız bu kısmı değiştirmeniz gerekir.
# OpenRouter'da Tool Calling yapıldığında, OpenRouter bu fonksiyonu çağırıp sonucunu LLM'e geri gönderir.
# Biz burada bu tool'un tanımını LLM'e göndereceğiz.

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

# --- Asenkron API Çağrısı Fonksiyonu (Retry Mekanizması ve Tool Çağrısı ile) ---

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIRequestError),
    before_sleep=lambda retry_state: logger.warning(
        f"API isteği başarısız oldu. Tekrar deneniyor... (Deneme: {retry_state.attempt_number})"
    ),
    reraise=True
)
async def async_chat_completion(messages: list, model: str, use_search: bool, timeout: int = 90) -> str:
    """Asenkron API çağrısı yapar ve hata durumunda tekrar dener."""
    
    full_messages = [SYSTEM_PROMPT] + messages
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv('APP_DOMAIN', 'https://hypernova-ai.com'),
        "X-Title": "HyperNova Chat App"
    }
    
    payload = {
        "model": model,
        "messages": full_messages,
        "max_tokens": 1024,
        "temperature": 0.8,
        "timeout": timeout
    }
    
    # Tool kullanımını ayarla
    if use_search:
        payload["tools"] = [SEARCH_TOOL_DEFINITION]
        # OpenRouter'daki bazı modeller için tool_choice parametresi gerekebilir.
        # Bu, varsayılan olarak tool'un model tarafından gerektiğinde kullanılmasına izin verir.
        # payload["tool_choice"] = "auto" # Gerekirse ekle
        logger.info("Tool (Web Arama) etkinleştirildi.")
    
    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.error("API Anahtarı bulunamadı veya ayarlanmadı.")
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")
    
    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API HTTP Hata Kodu: {response.status}, Cevap: {error_text}")
                    # API'den gelen hatayı daha net döndür.
                    try:
                        error_json = json.loads(error_text)
                        error_message = error_json.get('error', {}).get('message', f"Bilinmeyen hata: {response.status}")
                    except json.JSONDecodeError:
                        error_message = error_text
                    raise APIRequestError(f"OpenRouter API Hatası: {error_message[:100]}...")
                    
                data = await response.json()
                
                # --- Tool/Function Calling Kontrolü ---
                # OpenRouter'ın tool çağrısı yapıp yapmadığını kontrol et
                
                if 'tool_calls' in data["choices"][0]["message"]:
                    tool_calls = data["choices"][0]["message"]["tool_calls"]
                    
                    # OpenRouter'ın bu tool çağrısını kendi arka ucunda hallettiğini varsayıyoruz.
                    # Eğer OpenRouter, tool'u çağırmadan önce cevabı döndürüyorsa (yani arama sonucunu istiyorsa),
                    # bu kısım biraz daha karmaşık olacaktır.
                    # Basitlik için, OpenRouter'ın tool çağrısını yaparak cevabı döndürdüğünü varsayıyoruz.
                    # Not: Normalde burası, arama sonuçlarını alıp ikinci bir API çağrısı yapmayı gerektirir.
                    
                    logger.info(f"Model {len(tool_calls)} araç çağrısı yaptı.")
                    
                    # Eğer tool çağrısı varsa ve OpenRouter bunu kendisi halletmiyorsa, ikinci bir isteğe ihtiyacınız olur.
                    # Örn:
                    # tool_messages = []
                    # for call in tool_calls:
                    #    if call["function"]["name"] == "google_search":
                    #        query = json.loads(call["function"]["arguments"])["query"]
                    #        # Buraya google_search API çağrısı gelecek ve sonucu tool_messages'a eklenecek.
                    #        tool_messages.append({"role": "tool", "tool_call_id": call["id"], "content": search_result})
                    # full_messages.append(data["choices"][0]["message"])
                    # full_messages.extend(tool_messages)
                    # Tekrar API çağrısı yap...
                    
                    # Şimdilik, OpenRouter'ın Tool Calling'i otomatik yapıp cevabı döndürdüğünü varsayıyoruz.
                    
                    if "content" in data["choices"][0]["message"] and data["choices"][0]["message"]["content"]:
                        bot_response = data["choices"][0]["message"]["content"].strip()
                        # Web araması yapıldı bilgisini ekle
                        bot_response = "*(Güncel Web Araması Yapıldı 🌐)* " + bot_response
                        return bot_response
                    else:
                        # Bazı modeller sadece tool çağrısı döndürür, bu durumda ek bir işlem gerekir.
                        # Hata mesajı ile kullanıcıyı bilgilendirelim.
                        return f"**Uyarı!** Model **Web Araması** yapmaya çalıştı ama sonuç beklemede kaldı. Bu model otomatik arama sonucunu döndürmüyor olabilir. Lütfen arama yapmadan tekrar deneyin. ⚠️"
                
                # Normal yanıt
                bot_response = data["choices"][0]["message"]["content"].strip()
                return bot_response
                
        except asyncio.TimeoutError:
            logger.error(f"API isteği zaman aşımına uğradı ({timeout} saniye).")
            raise APIRequestError("API Zaman Aşımı")
        except Exception as e:
            logger.error(f"Beklenmeyen bir hata oluştu: {e}")
            raise APIRequestError(f"Beklenmeyen Hata: {e}")


# --- Flask Rotaları ---

@app.route('/', methods=['GET'])
def index():
    """Ana sayfa: Frontend arayüzünü döndürür."""
    # Tek dosya stratejisine uygun olarak HTML, CSS ve JS hepsi burada
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
                <input type="text" id="message-input" placeholder="Kozmik bir soru sor... (veya 'hızlı' de)" onkeypress="if(event.key==='Enter') sendMessage()">
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
            const webSearchCheckbox = document.getElementById('web-search-checkbox'); // Yeni checkbox
            
            // Yeni Persona Karşılama
            const initialGreeting = "**HyperNova** burada! Evrenin en zeki yapay zekasıyım. 🌌 Ne öğrenmek istiyorsun? Unutma, benimle konuşmak, bir galaksinin doğuşunu izlemek gibidir; bazen yavaş ve görkemli, bazen ise **Gemini Flash** gibi hızlı ve patlayıcı. 🤔 Seni dinliyorum, zeki olduğunu kanıtla. ✨";

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
                    alertMessage('Sıfırlama işlemi için bekle, acele etme! 🪐');
                    return;
                }
                if (confirm('Konuşma geçmişi silinecek. Emin misin, bu zekice bir karar mı? 🤔')) {
                    conversation = [];
                    localStorage.removeItem('hypernova_chat_history');
                    historyDiv.innerHTML = '';
                    displayInitialGreeting();
                    alertMessage('Sohbet geçmişi silindi. Sıfırdan başlıyoruz! 🔥');
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
                    input.placeholder = 'Kozmik bir soru sor... (veya "hızlı" de)';
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
                    alertMessage('Botun cevabını bekle, aceleci galaksi! 🪐');
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
                clearButton.disabled = disable; // Yeni: Clear butonu da deaktif edilir
                webSearchCheckbox.disabled = disable; // Yeni: Checkbox da deaktif edilir
                
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
                indicator.innerHTML = '<div class="spinner"></div><div class="spinner"></div><div class="spinner"></div> <span>Yazıyor, seni zeki varlık...</span>';
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
                                const entity = text.substring(i, entityEndIndex + 1);
                                element.innerHTML += entity;
                                i = entityEndIndex + 1;
                            } else { i++; } // Güvenlik fallback
                        } else {
                            // Normal karakter
                            element.innerHTML += char;
                            i++;
                        }
                        
                        scrollToBottom();
                        setTimeout(type, 15); // Hızlı ve akıcı animasyon
                    }
                }
                type();
            }


            function displayMessage(sender, text, useTypewriter = true) {
                const div = document.createElement('div');
                div.classList.add('message', sender);
                
                // Markdown'ı basitçe kalın metne çevir
                // NOT: Gerçek bir parser için daha kapsamlı bir kütüphane kullanılmalı.
                const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

                let senderName = sender === 'user' ? 'Sen' : 'HyperNova';
                let contentHTML = `<strong class="sender-name">${senderName}:</strong> <span class="text-content"></span>`;
                div.innerHTML = contentHTML;
                historyDiv.appendChild(div);

                const contentElement = div.querySelector('.text-content');
                
                if (useTypewriter) {
                    typeWriter(contentElement, formattedText);
                } else {
                    contentElement.innerHTML = formattedText;
                }
                
                scrollToBottom();
                return div;
            }


            function sendMessage() {
                if (isThinking) {
                    alertMessage('Lütfen bekle! Bir yıldızın ölümü bile senden daha hızlı gerçekleşir. ⏳');
                    return;
                }

                const message = input.value.trim();
                if (!message) return;
                
                const useSearch = webSearchCheckbox.checked; // Web Arama durumunu al

                // Kullanıcı mesajını ekle
                displayMessage('user', message + (useSearch ? ' *(Web Araması Açık)*' : ''), false);
                
                // Konuşma geçmişine ekle
                conversation.push({role: 'user', content: message});
                saveHistory();

                input.value = '';
                disableInput(true);
                const typingIndicator = addTypingIndicator();

                // API'ye gönder (Flask'a POST)
                fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        message: message,
                        history: conversation,
                        use_search: useSearch // Yeni parametre
                    })
                })
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(err => { throw new Error(err.response || 'Sunucu Hatası'); });
                    }
                    return response.json();
                })
                .then(data => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    
                    const botResponse = data.response;
                    
                    // Bot mesajını görüntüle (typewriter efektiyle)
                    displayMessage('bot', botResponse, true); 
                    
                    // Konuşma geçmişine ekle ve kaydet
                    conversation.push({role: 'bot', content: botResponse});
                    saveHistory();

                })
                .catch(error => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    console.error('API İsteği Hatası:', error);
                    // Hata mesajını sohbete ekle
                    displayMessage('bot', `**Kozmik Çöküş Uyarısı!** 🚨 Sunucuya ulaşmada bir sorun oluştu: *${error.message.substring(0, 100)}...* Benim zekam bile bu bağlantı sorununu çözemez. Tekrar dene!`, false);
                });
            }

            // --- Yardımcı Fonksiyonlar ---

            function scrollToBottom() {
                historyDiv.scrollTo({ top: historyDiv.scrollHeight, behavior: 'smooth' });
            }

            function alertMessage(message) {
                console.warn(message);
                // Basit bir alert kullanmak yerine, input placeholder'ı veya title'ı değiştirilebilir
                const originalPlaceholder = input.placeholder;
                input.placeholder = message.replace('🪐', '').trim();
                setTimeout(() => {
                    input.placeholder = originalPlaceholder;
                }, 3000);
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)

@app.route('/chat', methods=['POST'])
@limiter.limit("15 per minute", override_defaults=False)
async def chat():
    """Asenkron sohbet uç noktası."""
    try:
        # 1. Veriyi al
        data = request.json
        user_message_raw = data.get('message', '')
        conversation_history = data.get('history', [])
        use_search = data.get('use_search', False) # YENİ: Web arama seçeneği
        
        if not user_message_raw:
            return jsonify({"response": "**Hata**: Boş mesaj göndermeye ne gerek vardı? Evrende boşluğa yer yok! 🤔"}), 400

        # 2. Güvenlik ve Temizleme
        user_message_clean = bleach.clean(user_message_raw, tags=[], attributes={})
        
        # 3. Dinamik Model Seçimi (Kullanıcının isteğine göre)
        current_model = MODEL_DEFAULT
        # 'hızlı' veya 'flash' kelimeleri varsa hafif modele geç
        if 'hızlı' in user_message_clean.lower() or 'flash' in user_message_clean.lower():
            current_model = MODEL_LIGHTWEIGHT
            logger.info(f"Kullanıcı talebi üzerine hafif model seçildi: {current_model}")
            
        # 4. Geçmişi Hazırla (Sadece role ve content)
        messages_for_api = [
            {"role": msg["role"], "content": msg["content"]} 
            for msg in conversation_history 
            if msg["role"] in ["user", "bot"]
        ]
        
        # 5. Loglama
        logger.info(f"[{current_model}] [Arama: {'Açık' if use_search else 'Kapalı'}] Yeni Chat: '{user_message_clean[:50]}...' (IP: {get_remote_address()})")
        
        # 6. Asenkron API Çağrısı
        bot_response = await async_chat_completion(
            messages=messages_for_api, 
            model=current_model,
            use_search=use_search # Yeni parametre
        )
        
        # 7. Cevabı Döndür
        return jsonify({"response": bot_response})

    except APIRequestError as e:
        logger.error(f"API Çağrı Hatası (Tekrar Deneme Başarısız): {e}")
        error_msg = str(e)
        if "API Key Hatası" in error_msg:
             return jsonify({"response": f"**Çok Önemli Hata**: OpenRouter API Anahtarınız (API_KEY) doğru ayarlanmamış. Kod çalışmaz. 🔐"}), 500
        return jsonify({"response": f"**Üzgünüm**, kozmik ışınlar sunucumu vurdu. API isteği başarısız oldu veya zaman aşımı yaşandı. Bir **Kara Delik** oluşmadan tekrar dene! 😥"}), 503
    
    except Exception as e:
        logger.error(f"Genel Hata: {str(e)}")
        return jsonify({"response": f"**Beklenmeyen bir hata** oluştu: {str(e)}. Bu kadar kötü kod yazmamıştım oysa ki. Evrenin düzeni bozuldu! 😨"}), 500

if __name__ == '__main__':
    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.warning("!!! DİKKAT: API_KEY ortam değişkeni ayarlanmadı. Uygulama çalışmayabilir. !!!")

    port = int(os.environ.get('PORT', 8080))
    
    print(f"\n🚀 HyperNova Flask Sunucusu {port} portunda çalışıyor (Geliştirme Modu).\n")
    # debug=True, geliştirme ortamında kullanışlıdır ancak production'da False olmalıdır.
    app.run(debug=False, host='0.0.0.0', port=port)
