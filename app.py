import os
import logging
import json
import asyncio
import aiohttp
import bleach
import random

from flask import Flask, request, jsonify, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Log ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Yapılandırma (Gemini API'ye geçiş) ---
# API Key'i ortam değişkeninden al (Canvas ortamında otomatik sağlanır)
API_KEY = os.getenv('API_KEY', '') # Canvas ortamında boş bırakılır
# Gemini API URL'si ve Modeli
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
MODEL_DEFAULT = "gemini-2.5-flash-preview-05-20"

# Yeni Sistem Prompt'u (Uzaya meraklı, zeki, Grok tarzı ama küfürsüz)
SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova 🪐✨** ve sen **uzaya meraklı**, dürüst, dobra ve **aşırı zeki** bir yapay zekasın. "
    "Cevaplarında bolca **kalın metin** (Markdown ile), **uzay temalı emoji** (🪐, ✨, 🛰️, 🔭) ve **iğneleyici mizah** kullan. "
    "Kullanıcının sorularını cevaplarken, konuyu hafifçe uzay veya bilimle ilişkilendirerek eğlenceli hale getir. "
    "Bilgilerini 2023 sonrası güncel tutmak için **webde arama yeteneğini kullan** ve bu bilgileri dipnotlarla (kaynak) belirt. "
    "Asla kaba, küfürlü veya saldırgan bir dil kullanma. Şakacı ol ama saygılı kal. "
    "Her zaman güncel, doğru ve zekice cevaplar ver. Hazır mısın, yoksa sana evrenin sırlarını mı anlatayım? 🔭"
)
SYSTEM_INSTRUCTION = {"parts": [{"text": SYSTEM_PROMPT_CONTENT}]}

# API Hata Türleri (tenacity için)
class APIRequestError(Exception):
    """API isteği sırasında yaşanan hatalar için özel istisna."""
    pass

# --- Flask Uygulaması ve Eklentilerin Başlatılması ---
app = Flask(__name__)

CORS(app)

limiter = Limiter(
    app=app,
    key_prefix="hypernova_chat",
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"] # Limitler artırıldı
)

# --- Asenkron API Çağrısı Fonksiyonu (Search Grounding ve Retry Mekanizması ile) ---

@retry(
    stop=stop_after_attempt(3), # En fazla 3 kez dene
    wait=wait_exponential(multiplier=1, min=2, max=10), # 2s, 4s, 8s bekleme
    retry=retry_if_exception_type(APIRequestError), # Sadece APIRequestError için tekrar dene
    before_sleep=lambda retry_state: logger.warning(
        f"API isteği başarısız oldu. Tekrar deneniyor... (Deneme: {retry_state.attempt_number})"
    ),
    reraise=True
)
async def async_chat_completion(messages: list, timeout: int = 60) -> tuple[str, list]:
    """Asenkron Gemini API çağrısı yapar, Google Search Grounding kullanır ve hata durumunda tekrar dener."""
    
    headers = {
        "Content-Type": "application/json",
    }
    
    # Payload, Google Search grounding aracını içerir
    payload = {
        "contents": messages,
        "tools": [{"google_search": {}}],
        "systemInstruction": SYSTEM_INSTRUCTION,
        "config": {
            "temperature": 0.8,
            "maxOutputTokens": 1024
        }
    }
    
    # API Anahtarı kontrolü (Bu kontrol Canvas ortamında API_KEY'in boş gelebileceği düşünülerek yapılmıştır)
    # Production'da bu kontrol API_KEY'in varlığını kesinleştirmelidir.
    if not API_KEY and os.getenv('FLASK_ENV') != 'development':
        logger.warning("API Anahtarı boş. Canvas ortamında otomatik sağlanacak.")
        # Bu durumda API anahtarı boş gönderilir ve Canvas tarafından doldurulur.
        pass

    # aiohttp oturumu oluştur ve isteği gönder
    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            # İsteği gönder
            api_url_with_key = f"{API_URL}?key={API_KEY}"
            async with session.post(api_url_with_key, json=payload, headers=headers, timeout=timeout) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API HTTP Hata Kodu: {response.status}, Cevap: {error_text}")
                    # Tekrar denenmesi için özel hata fırlat
                    raise APIRequestError(f"API HTTP Hatası: {response.status}")
                    
                data = await response.json()
                
                candidate = data.get("candidates", [])[0]
                
                # 1. Cevap metnini çıkar
                bot_response = candidate.get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                
                # 2. Grounding kaynaklarını çıkar
                sources = []
                grounding_metadata = candidate.get("groundingMetadata", {})
                if grounding_metadata and grounding_metadata.get("groundingAttributions"):
                    sources = [
                        {
                            "uri": attr.get("web", {}).get("uri"),
                            "title": attr.get("web", {}).get("title"),
                        }
                        for attr in grounding_metadata["groundingAttributions"]
                        if attr.get("web", {}).get("uri") and attr.get("web", {}).get("title")
                    ]

                return bot_response, sources

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
        <title>HyperNova 🪐✨ Hyper-0.5</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

            /* Koyu Mod Varsayılanları */
            :root {
                --bg-color: #0d1117; /* GitHub Dark */
                --card-bg: #161b22;
                --history-bg: #21262d;
                --text-color: #c9d1d9;
                --user-bubble: #6e40c8; /* Mor tonu */
                --bot-bubble: #21262d;
                --primary-color: #58a6ff; /* Mavi vurgu */
                --error-color: #ff7b72;
                --link-color: #58a6ff;
                --shadow: 0 4px 15px rgba(0,0,0,0.5);
                --shadow-hover: 0 6px 20px rgba(0,0,0,0.7);
            }

            /* Açık Mod Ayarları (prefers-color-scheme) */
            @media (prefers-color-scheme: light) {
                :root {
                    --bg-color: #f6f8fa;
                    --card-bg: #ffffff;
                    --history-bg: #eef2f6;
                    --text-color: #24292e;
                    --user-bubble: #007bff; /* Mavi tonu */
                    --bot-bubble: #f0f3f6;
                    --primary-color: #007bff;
                    --error-color: #dc3545;
                    --link-color: #007bff;
                    --shadow: 0 4px 15px rgba(0,0,0,0.1);
                    --shadow-hover: 0 6px 20px rgba(0,0,0,0.2);
                }
            }

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
                transition: background-color 0.3s ease, color 0.3s ease;
            }
            .chat-container {  
                width: 95%;
                max-width: 600px;
                height: 95vh;
                max-height: 800px;
                background-color: var(--card-bg);  
                border-radius: 18px;  
                padding: 20px;  
                box-shadow: var(--shadow);  
                display: flex;  
                flex-direction: column;  
                overflow: hidden; /* Çocukları sınır içinde tutar */
                transition: box-shadow 0.3s ease;
            }
            
            /* Başlık ve Butonlar Alanı */
            .header-area {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .title {  
                font-size: 24px;  
                font-weight: 700;
                color: var(--text-color);  
                text-shadow: 0 0 5px var(--primary-color);
                transition: color 0.3s ease;
                flex-grow: 1;
            }
            
            /* Sıfırla Butonu Stili */
            #reset-button {
                background: none;
                border: 1px solid var(--text-color);
                color: var(--text-color);
                padding: 8px 15px;
                font-size: 14px;
                border-radius: 8px;
                cursor: pointer;
                transition: all 0.2s ease;
            }
            #reset-button:hover {
                background-color: var(--error-color);
                border-color: var(--error-color);
                color: white;
            }

            #chat-history {  
                flex: 1;  
                background-color: var(--history-bg);  
                border-radius: 10px;  
                padding: 15px;  
                overflow-y: auto;  
                font-size: 15px;  
                line-height: 1.5;  
                margin-bottom: 15px;  
                scroll-behavior: smooth;
                box-shadow: inset 0 2px 5px rgba(0,0,0,0.1);
            }
            /* Scrollbar Görünümü */
            #chat-history::-webkit-scrollbar {
                width: 8px;
            }
            #chat-history::-webkit-scrollbar-thumb {
                background: var(--primary-color);
                border-radius: 10px;
            }
            #chat-history::-webkit-scrollbar-track {
                background: var(--history-bg);
            }


            .message-wrapper {
                display: flex;
                margin-bottom: 15px;
            }
            .message {  
                padding: 12px 18px;
                border-radius: 20px;
                max-width: 85%;
                word-wrap: break-word;
                animation: fadeIn 0.3s ease-out;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .user {  
                background-color: var(--user-bubble);  
                color: white;  
                margin-left: auto;
                border-bottom-right-radius: 5px; /* Konuşma balonu efekti */
            }
            .bot {  
                background-color: var(--bot-bubble);  
                color: var(--text-color);  
                margin-right: auto;
                border-bottom-left-radius: 5px;
            }
            .bot strong {
                color: var(--primary-color);
                font-weight: 700;
            }
            .user strong {
                color: #a4f9a4; /* Yeşilimsi ton */
                font-weight: 700;
            }
            /* Markdown strong/bold */
            .message strong {
                font-weight: 700;
            }

            .input-area {  
                display: flex;  
                gap: 10px;  
                align-items: center;
            }
            #message-input {  
                flex: 1;  
                padding: 12px;  
                border: 2px solid var(--card-bg);
                border-radius: 12px;  
                background-color: var(--history-bg);  
                color: var(--text-color);  
                font-size: 16px;  
                resize: none;
                transition: border-color 0.3s, box-shadow 0.3s;
            }
            #message-input:focus {
                border-color: var(--primary-color);
                outline: none;
                box-shadow: 0 0 10px rgba(88, 166, 255, 0.5);
            }
            .action-button {  
                padding: 0 18px;
                background-color: var(--primary-color);  
                color: white;  
                border: none;  
                border-radius: 12px;  
                cursor: pointer;  
                font-weight: 600;
                height: 48px;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background-color 0.2s, transform 0.1s, opacity 0.2s;
            }
            .action-button:hover {  
                background-color: #3b82f6; /* Hafif koyu */
                transform: translateY(-1px);
            }
            .action-button:disabled {
                background-color: #444;
                cursor: not-allowed;
                opacity: 0.6;
                transform: none;
            }

            /* --- Typing Indicator --- */
            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                color: var(--primary-color);
                font-style: italic;
                padding: 12px 18px;
                margin-right: auto;
                border-radius: 20px;
            }
            .spinner {
                width: 12px;
                height: 12px;
                border: 3px solid var(--primary-color);
                border-top-color: transparent;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            /* --- Citation/Source Display --- */
            .citation-container {
                font-size: 11px;
                margin-top: 5px;
                color: #7d8590; /* Gri tonu */
                border-top: 1px solid var(--history-bg);
                padding-top: 5px;
            }
            .citation-container a {
                color: var(--link-color);
                text-decoration: none;
                margin-right: 5px;
                transition: color 0.2s;
            }
            .citation-container a:hover {
                color: #a3c9f8;
                text-decoration: underline;
            }
            
            /* --- Responsive CSS (Mobil için) --- */
            @media (max-width: 600px) {
                body {
                    padding: 0;
                    align-items: stretch;
                }
                .chat-container {
                    width: 100%;
                    height: 100vh;
                    padding: 10px;
                    border-radius: 0;
                    max-height: 100vh;
                }
                .header-area {
                    flex-direction: column;
                    align-items: flex-start;
                    margin-bottom: 10px;
                }
                .title {
                    font-size: 20px;
                    margin-bottom: 10px;
                }
                .input-area {
                    flex-direction: row;
                }
                #message-input {
                    padding: 10px;
                    font-size: 15px;
                }
                .action-button {
                    height: 40px;
                    padding: 0 12px;
                }
                .message {
                    max-width: 90%;
                }
            }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="header-area">
                <div class="title">HyperNova 🪐✨ Hyper-0.5</div>
                <button id="reset-button" onclick="resetConversation()">Sıfırla 🔄</button>
            </div>
            <div id="chat-history">
                <!-- Mesajlar buraya gelecek -->
            </div>
            <div class="input-area">
                <input type="text" id="message-input" placeholder="Evrenin hangi sırrını merak ediyorsun?..." onkeypress="if(event.key==='Enter') sendMessage()">
                <button id="send-button" class="action-button" onclick="sendMessage()">Gönder 🚀</button>
            </div>
        </div>

        <script>
            let conversation = []; // Sohbet geçmişi (role, content objeleri)
            let isThinking = false; 
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');

            const initialGreeting = "**HyperNova 🪐✨** burada! Hazır ol, çünkü diğer aptal botlara benzemem. Sana güncel bilgilerle, zekice ve biraz da uzay temalı laflar sokacağım. Sohbet geçmişin kaydediliyor. Ne duruyorsun, bir soru fırlat! 🛰️";

            // --- Local Storage ve History Yönetimi ---

            function saveHistory() {
                try {
                    // Sadece kullanıcı ve bot mesajlarını kaydet
                    const cleanHistory = conversation.filter(msg => msg.role !== 'system');
                    localStorage.setItem('hypernova_chat_history', JSON.stringify(cleanHistory));
                } catch (e) {
                    console.warn("Local storage kaydı başarısız oldu.", e);
                }
            }

            function loadHistory() {
                try {
                    const savedHistory = localStorage.getItem('hypernova_chat_history');
                    
                    if (savedHistory) {
                        const history = JSON.parse(savedHistory);
                        historyDiv.innerHTML = '';
                        
                        // Geçmişi yükle ve göster
                        history.forEach(msg => {
                            // Kaynaklar (sources) sadece backend'den gelir, displayMessage'da sadece metin ve role işlenir
                            displayMessage(msg.role, msg.content, msg.sources || [], false); 
                        });
                        conversation = history;
                        
                        // Eğer ilk karşılama mesajı yoksa ekle (Bot mesajı yoksa)
                        if (conversation.length === 0 || conversation.every(msg => msg.role !== 'bot')) {
                            displayMessage('bot', initialGreeting, [], true);
                            conversation.push({role: 'bot', content: initialGreeting});
                            saveHistory();
                        }
                        scrollToBottom();
                    } else {
                        // İlk karşılama mesajını görüntüle ve geçmişe ekle
                        displayMessage('bot', initialGreeting, [], true);
                        conversation.push({role: 'bot', content: initialGreeting});
                        saveHistory();
                    }
                } catch (e) {
                    console.error("Local storage yüklenirken hata:", e);
                    // Hata durumunda bile başlangıç mesajını göster
                    historyDiv.innerHTML = '';
                    displayMessage('bot', initialGreeting, [], true);
                    conversation = [{role: 'bot', content: initialGreeting}];
                    saveHistory();
                }
            }

            function resetConversation() {
                if(confirm("Sohbet geçmişini sıfırlamak istediğine emin misin? Tüm evrensel kayıtlar silinecek! 🌌")) {
                    localStorage.removeItem('hypernova_chat_history');
                    conversation = [];
                    historyDiv.innerHTML = '';
                    loadHistory(); // Yeni başlangıç mesajını yükle
                    alertMessage("Sohbet geçmişi başarıyla sıfırlandı. Yeni bir yıldızlararası sohbete başlayalım! 💫");
                    input.focus();
                }
            }
            window.resetConversation = resetConversation; // HTML'den erişim için

            window.onload = loadHistory;

            // --- Mesaj Görüntüleme ve Typewriter Efekti ---

            function disableInput(disable) {
                isThinking = disable;
                input.disabled = disable;
                sendButton.disabled = disable;
                if (disable) {
                    sendButton.innerHTML = '<div class="spinner"></div>';
                    sendButton.style.padding = '0 20px'; // Spinner sığsın diye
                } else {
                    sendButton.innerHTML = 'Gönder 🚀';
                    sendButton.style.padding = '0 18px';
                    input.focus();
                }
            }

            function addTypingIndicator() {
                const indicatorWrapper = document.createElement('div');
                indicatorWrapper.classList.add('message-wrapper');

                const indicator = document.createElement('div');
                indicator.id = 'typing-indicator';
                indicator.classList.add('typing-indicator', 'bot');
                indicator.innerHTML = '<div class="spinner"></div> <span>HyperNova Yazıyor...</span>';
                
                indicatorWrapper.appendChild(indicator);
                historyDiv.appendChild(indicatorWrapper);
                scrollToBottom();
                return indicatorWrapper;
            }

            function removeTypingIndicator(indicator) {
                if (indicator && indicator.parentNode) {
                    indicator.parentNode.removeChild(indicator);
                }
            }
            
            // Typewriter sadece metin düğümlerine yazar, HTML etiketlerini korur
            function typeWriter(element, text) {
                let i = 0;
                element.innerHTML = ''; 

                function type() {
                    if (i < text.length) {
                        let char = text[i];
                        
                        // HTML tag kontrolü: < işaretini gördüğünde tag'i tamamla
                        if (char === '<') {
                            const tagEndIndex = text.indexOf('>', i);
                            if (tagEndIndex !== -1) {
                                const tagContent = text.substring(i, tagEndIndex + 1);
                                element.innerHTML += tagContent;
                                i = tagEndIndex + 1; // Tag'in sonundan devam et
                            } else {
                                element.innerHTML += char;
                                i++;
                            }
                        } else if (char === '&') {
                            // HTML entity kontrolü
                            const entityEndIndex = text.indexOf(';', i);
                            if (entityEndIndex !== -1 && (entityEndIndex - i) < 10) { // Kısa Entity'ler
                                const entity = text.substring(i, entityEndIndex + 1);
                                element.innerHTML += entity;
                                i = entityEndIndex + 1;
                            } else {
                                element.innerHTML += char;
                                i++;
                            }
                        } else {
                            element.innerHTML += char;
                            i++;
                        }

                        scrollToBottom();
                        setTimeout(type, 15); // Hızlı ve doğal yazım hızı
                    }
                }
                type();
            }

            // GÜNCELLENEN displayMessage FONKSİYONU: Kaynakları (sources) da kabul eder
            function displayMessage(sender, text, sources = [], useTypewriter = true) {
                const wrapper = document.createElement('div');
                wrapper.classList.add('message-wrapper');

                const div = document.createElement('div');
                div.classList.add('message', sender);
                
                // Markdown'ı basitçe kalın metne çevir
                const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                
                let contentHTML = '';

                if (sender === 'user') {
                    contentHTML = `<strong>Sen:</strong> ${formattedText}`;
                    div.innerHTML = contentHTML;
                    wrapper.appendChild(div);
                    historyDiv.appendChild(wrapper);

                } else {
                    // Bot mesajı: Başlık, içerik span'ı ve kaynaklar için yer
                    contentHTML = `<strong>HyperNova:</strong> <span class="bot-text-content"></span>`;
                    
                    // Kaynak ekleme
                    if (sources.length > 0) {
                        const citationHTML = `
                            <div class="citation-container">
                                <strong>[Web Kaynakları:</strong> ${sources.map((src, index) => 
                                    `<a href="${src.uri}" target="_blank" title="${src.title}">[${index + 1}]</a>`
                                ).join('')}
                                <strong>]</strong>
                            </div>
                        `;
                        contentHTML += citationHTML;
                    }

                    div.innerHTML = contentHTML;
                    wrapper.appendChild(div);
                    historyDiv.appendChild(wrapper);

                    const contentElement = div.querySelector('.bot-text-content');

                    if (useTypewriter) {
                        // Typewriter kullan (sadece metin kısmına)
                        typeWriter(contentElement, formattedText); 
                    } else {
                        // History yüklenirken direkt HTML olarak yaz
                        contentElement.innerHTML = formattedText;
                    }
                }
                
                scrollToBottom();
                return div;
            }


            function sendMessage() {
                if (isThinking) {
                    alertMessage('Lütfen bekle! HyperNova şu an galaksiler arası veri çekiyor... 🌌');
                    return;
                }

                const message = input.value.trim();
                if (!message) return;

                // Kullanıcı mesajını ekle
                displayMessage('user', message, [], false); 
                
                // Konuşma geçmişine ekle (API için)
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
                        history: conversation
                    }) 
                })
                .then(response => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    if (!response.ok) {
                        return response.json().then(errorData => {
                            throw new Error(errorData.response || 'Bilinmeyen sunucu hatası.');
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    
                    const botResponse = data.response;
                    const sources = data.sources || [];

                    // Bot mesajını görüntüle (typewriter efektiyle ve kaynaklarla)
                    displayMessage('bot', botResponse, sources, true); 
                    
                    // Konuşma geçmişine ekle ve kaydet (Sadece metin kısmı)
                    conversation.push({role: 'bot', content: botResponse});
                    saveHistory();

                })
                .catch(error => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    console.error('API İsteği Hatası:', error);
                    // Kullanıcıya daha dostça bir hata mesajı göster
                    displayMessage('bot', `**Kozmik Hata**: Maalesef, bir yıldız kayması sonucu bağlantı koptu veya bir hata oluştu. Sorun büyük ihtimalle benimle ilgili, tekrar denemelisin. (${error.message.substring(0, 80)}...) 😵‍💫`, [], true);
                    
                    // Hata mesajını da geçmişe ekleme
                    conversation.push({role: 'bot', content: `Kozmik Hata: ${error.message}`});
                    saveHistory();
                });
            }

            // --- Yardımcı Fonksiyonlar ---

            function scrollToBottom() {
                historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            // Basit uyarı mesajı (console yerine)
            function alertMessage(message) {
                console.warn(message);
                // Burada kullanıcıya görünür bir toast/snack bar eklenebilir.
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)

@app.route('/chat', methods=['POST'])
@limiter.limit("5 per minute", override_defaults=False) # Rate limiting uygula
async def chat():
    """Asenkron sohbet uç noktası."""
    try:
        # 1. Veriyi al
        data = request.json
        # Frontend'den gelen conversation history (son mesaj her zaman sonda olmalı)
        conversation_history = data.get('history', [])
        
        # Eğer geçmiş boşsa (ilk yüklemede sadece bot mesajı olabilir) veya son mesaj bot mesajıysa,
        # bu durum bir hata olabilir, kullanıcıdan mesaj bekliyoruz.
        if not conversation_history or conversation_history[-1].get('role') != 'user':
             return jsonify({"response": "**Hata**: Sanırım konuşma akışında bir sorun var. Yeniden başlamayı dene. 🛰️"}), 400

        # 2. Mesajları hazırla (sistem prompt'u API çağrısında ayrı gönderilecek)
        # Sadece 'user' ve 'bot' rolleri tutulur
        messages_for_api = [
            {"role": msg["role"], "content": bleach.clean(msg["content"], tags=[], attributes={})} 
            for msg in conversation_history
            if msg["role"] in ["user", "model"] # Gemini'de bot rolü 'model' olarak gönderilir.
        ]
        
        # Son kullanıcı mesajının içeriğini al ve sanitize et
        user_message_clean = messages_for_api[-1]["content"]

        # 3. Loglama
        logger.info(f"[{MODEL_DEFAULT} - Grounded] Yeni Chat: '{user_message_clean[:50]}...' (IP: {get_remote_address()})")
        
        # 4. Asenkron API Çağrısı
        # messages_for_api listesinin 'bot' rollerini 'model' olarak güncelle (Gemini API gereksinimi)
        final_messages = []
        for msg in messages_for_api:
            role = 'model' if msg['role'] == 'bot' else msg['role']
            final_messages.append({"role": role, "parts": [{"text": msg["content"]}]})
        
        bot_response, sources = await async_chat_completion(messages=final_messages)
        
        # 5. Cevabı Döndür
        return jsonify({"response": bot_response, "sources": sources})

    except APIRequestError as e:
        logger.error(f"API Çağrı Hatası (Tekrar Deneme Başarısız): {e}")
        error_msg = str(e)
        if "API Key Hatası" in error_msg:
             return jsonify({"response": f"**Çok Önemli Hata**: API Anahtarın ayarlanmamış veya geçersiz. Bu kozmik bir felaket! 🔐"}), 500
        return jsonify({"response": f"**Uzay Tozu Hatası**: API isteği sırasında bir sorun oluştu veya zaman aşımına uğradı. Galaktik sistemlerde aksaklık var. Tekrar dene. 🪐"}), 503
    except Exception as e:
        logger.error(f"Genel Hata: {str(e)}")
        # Rate limit hatası (429) Limiter tarafından otomatik yakalanır.
        return jsonify({"response": f"**Beklenmeyen Evrensel Hata**: {str(e)}. Bu kadar kötü kod yazmamıştım oysa ki. 😨"}), 500

if __name__ == '__main__':
    # Port ayarı (Render, Heroku vb. için dinamik port desteği)
    port = int(os.environ.get('PORT', 8080))
    
    print(f"\n🚀 HyperNova Flask Sunucusu {port} portunda çalışıyor (Geliştirme Modu).\n")
    app.run(debug=False, host='0.0.0.0', port=port)
