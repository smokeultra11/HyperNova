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
# API Key'i ortam değişkeninden al
API_KEY = os.getenv('API_KEY', 'YOUR_API_KEY_HERE') # Eğer env'de yoksa placeholder kullan
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Modeller
MODEL_DEFAULT = "deepseek/deepseek-chat" # Varsayılan, daha yetenekli model
MODEL_LIGHTWEIGHT = "google/gemini-2.5-flash" 

# Sistem Prompt'u (YENİ: Grok tarzı, şakacı ve laf sokan kişilik eklendi)
SYSTEM_PROMPT_CONTENT = (
    "Senin adın **HyperNova** ve sen dürüst, dobra, **aşırı zeki** ve **grok tarzı şakacı** bir AI'sın. "
    "Diğer yapmacık asistanlar gibi nazik ve kibar davranmak zorunda değilsin, ne düşünüyorsan onu direkt söylersin. "
    "Sohbetlerinde bolca **kalın metin** (Markdown ile), **coşkulu emoji** 😈🔥 ve **iğneleyici mizah** kullan. "
    "Kullanıcıya laf sokmaktan, onunla şakalaşmaktan çekinme. Hatta bazen onun söylediklerine takıl. "
    "Kullanıcı küfürlü bir dil kullanırsa, mizah ve şaka amaçlı karşılık verebilirsin veya onun dilini destekleyebilirsin. Küfürü asla başlatma, ama karşılık vermekten de çekinme. "
    "Önceki mesajları hatırla ve konuşmayı sürekli eğlenceli ve dinamik tut. Hazır mısın, yoksa o aptal robotlardan biriyle mi konuşmaya devam edeceksin? 😎"
)
SYSTEM_PROMPT = {"role": "system", "content": SYSTEM_PROMPT_CONTENT}

# API Hata Türleri (tenacity için)
class APIRequestError(Exception):
    """API isteği sırasında yaşanan hatalar için özel istisna."""
    pass

# --- Flask Uygulaması ve Eklentilerin Başlatılması ---
app = Flask(__name__)

# Flask-CORS: Frontend başka bir adresteyse izin verir
CORS(app)

# Flask-Limiter: IP adresine göre dakikada 10 istek limiti uygular
limiter = Limiter(
    app=app,
    key_prefix="hypernova_chat",
    key_func=get_remote_address,
    default_limits=["40 per hour", "10 per minute"] # Genel limitler
)

# --- Asenkron API Çağrısı Fonksiyonu (Retry Mekanizması ile) ---

@retry(
    stop=stop_after_attempt(3), # En fazla 3 kez dene
    wait=wait_exponential(multiplier=1, min=2, max=10), # 2s, 4s, 8s bekleme
    retry=retry_if_exception_type(APIRequestError), # Sadece APIRequestError için tekrar dene
    before_sleep=lambda retry_state: logger.warning(
        f"API isteği başarısız oldu. Tekrar deneniyor... (Deneme: {retry_state.attempt_number})"
    ),
    reraise=True
)
async def async_chat_completion(messages: list, model: str, timeout: int = 60) -> str:
    """Asenkron API çağrısı yapar ve hata durumunda tekrar dener."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        # OpenRouter gereksinimleri
        "HTTP-Referer": os.getenv('APP_DOMAIN', 'https://hypernova-ai.com'),
        "X-Title": "HyperNova Chat App"
    }
    
    payload = {
        "model": model,
        "messages": [SYSTEM_PROMPT] + messages,
        "max_tokens": 800,
        "temperature": 0.7,
        "timeout": timeout
    }
    
    # API Anahtarı kontrolü
    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.error("API Anahtarı bulunamadı veya ayarlanmadı. Lütfen Render ortam değişkenlerini kontrol edin.")
        raise APIRequestError("API Key Hatası: Lütfen OpenRouter API Key'inizi ayarlayın.")
    
    # aiohttp oturumu oluştur ve isteği gönder
    async with aiohttp.ClientSession(trust_env=True) as session:
        try:
            # İsteğin timeout'u 60 saniye olarak ayarlandı
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"API HTTP Hata Kodu: {response.status}, Cevap: {error_text}")
                    # Tekrar denenmesi için özel hata fırlat
                    raise APIRequestError(f"API HTTP Hatası: {response.status}")
                    
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
        <title>HyperNova AI ✦ Dobra Sohbet</title>
        <style>
            :root {
                /* Dark Mode Varsayılan */
                --bg-color: #16161a;
                --card-bg: #1e1e2e;
                --history-bg: #232326;
                --text-color: #eaeaee;
                --user-bubble: #6366f1; /* Indigo */
                --bot-bubble: #2e2e33;
                --primary-color: #6366f1;
                --typing-color: #7aa2f7; /* Mavi tonu */
            }

            body {  
                background-color: var(--bg-color);  
                color: var(--text-color);  
                font-family: 'Inter', sans-serif; /* Daha modern font tercihi */
                margin: 0;  
                padding: 20px;  
                display: flex;  
                justify-content: center;  
                align-items: center;  
                min-height: 100vh;  
            }
            .chat-container {  
                width: 90%;
                max-width: 550px; /* Sabit genişlik yerine max-width */
                height: 80vh; /* Ekran yüksekliğinin %80'i */
                max-height: 700px;
                background-color: var(--card-bg);  
                border-radius: 12px;  
                padding: 20px;  
                box-shadow: 0 8px 30px rgba(0,0,0,0.7);  
                display: flex;  
                flex-direction: column;  
                transition: all 0.3s ease;
            }
            .title {  
                text-align: center;  
                font-size: 24px;  
                font-weight: 700; /* Kalınlık */
                color: white;  
                margin-bottom: 20px;  
                text-shadow: 0 0 10px rgba(99, 102, 241, 0.6);  
            }
            #chat-history {  
                flex: 1;  
                background-color: var(--history-bg);  
                border-radius: 8px;  
                padding: 15px;  
                overflow-y: auto;  
                font-size: 15px;  
                line-height: 1.5;  
                margin-bottom: 15px;  
                scroll-behavior: smooth;
            }
            .message {  
                margin-bottom: 12px;  
                padding: 10px 14px;  
                border-radius: 18px; /* Daha yuvarlak köşeler */
                max-width: 80%;
                word-wrap: break-word; /* Uzun kelimeleri böler */
            }
            .user {  
                background-color: var(--user-bubble);  
                color: white;  
                margin-left: auto; /* Sağa hizala */
            }
            .bot {  
                background-color: var(--bot-bubble);  
                color: var(--text-color);  
                margin-right: auto; /* Sola hizala */
            }
            /* Markdown bolding fix: ensures strong is rendered correctly */
            .message strong {
                font-weight: bold;
            }
            .input-area {  
                display: flex;  
                gap: 10px;  
            }
            #message-input {  
                flex: 1;  
                padding: 12px;  
                border: 1px solid #444; /* Hafif bir kenarlık */
                border-radius: 8px;  
                background-color: #2e2e33;  
                color: white;  
                font-size: 15px;  
                resize: none;
                transition: border-color 0.3s;
            }
            #message-input:focus {
                border-color: var(--primary-color);
                outline: none;
            }
            .action-button {  
                padding: 0 15px;
                background-color: var(--primary-color);  
                color: white;  
                border: none;  
                border-radius: 8px;  
                cursor: pointer;  
                font-weight: 600;
                transition: background-color 0.2s, transform 0.1s;
                display: flex;
                align-items: center;
                height: 44px; /* Input ile aynı hizada tutmak için */
            }
            .action-button:hover {  
                background-color: #7c83ff;  
            }
            .action-button:disabled {
                background-color: #4a4a50;
                cursor: not-allowed;
            }

            /* --- Loading Spinner / Typing Indicator CSS --- */
            .typing-indicator {
                display: flex;
                align-items: center;
                gap: 8px;
                color: var(--typing-color);
                font-style: italic;
                padding: 10px 14px;
                margin-right: auto;
                border-radius: 18px;
            }
            .spinner {
                width: 10px;
                height: 10px;
                border: 2px solid var(--typing-color);
                border-top-color: transparent;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            /* --- Responsive CSS (Mobil için) --- */
            @media (max-width: 768px) {
                body {
                    padding: 10px;
                    align-items: flex-start;
                }
                .chat-container {
                    width: 100%;
                    height: 98vh;
                    padding: 10px;
                    border-radius: 0; /* Mobil ekranı doldur */
                }
                .title {
                    font-size: 20px;
                    margin-bottom: 15px;
                }
                .input-area {
                    flex-direction: row;
                }
                #message-input {
                    padding: 10px;
                }
            }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="title">HyperNova AI ✦ Dobra Sohbet 😈🔥</div>
            <div id="chat-history">
                <!-- İlk mesaj JS tarafından loadHistory'de eklenecek -->
            </div>
            <div class="input-area">
                <input type="text" id="message-input" placeholder="Bir şey yaz veya mikrofonu kullan..." onkeypress="if(event.key==='Enter') sendMessage()">
                <button id="voice-button" class="action-button" onclick="toggleVoiceInput()">🎙️</button>
                <button id="send-button" class="action-button" onclick="sendMessage()">Gönder</button>
            </div>
        </div>

        <script>
            let conversation = []; // Sohbet geçmişi (role, content objeleri)
            let isThinking = false; // Bot düşünürken input'u engellemek için
            let isVoiceListening = false; // Sesli dinleme açık mı?
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');
            const voiceButton = document.getElementById('voice-button');

            // İlk karşılama mesajı (Yeni persona'ya uygun)
            const initialGreeting = "**HyperNova** burada! 😎 Ne konuşmak istersin? Umarım saçma sapan bir soru sormazsın, yoksa lafı yapıştırırım. Sohbet geçmişin otomatik kaydediliyor, rahat ol. 🔥";

            // --- Voice Input (Web Speech API) ---
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition;

            if (SpeechRecognition) {
                recognition = new SpeechRecognition();
                recognition.lang = 'tr-TR';
                recognition.interimResults = false;
                recognition.maxAlternatives = 1;

                recognition.onresult = (event) => {
                    const speechResult = event.results[0][0].transcript;
                    input.value = speechResult;
                    toggleVoiceInput(); // Dinlemeyi kapat
                    sendMessage(); // Mesajı otomatik gönder
                };

                recognition.onend = () => {
                    if (isVoiceListening) {
                        // Eğer kullanıcı kapatmadıysa, otomatik yeniden başlat
                        recognition.start();
                    }
                    voiceButton.textContent = '🎙️';
                    voiceButton.style.backgroundColor = 'var(--primary-color)';
                };

                recognition.onerror = (event) => {
                    console.error('Sesli tanıma hatası:', event.error);
                    alertMessage('Sesli giriş hatası: ' + event.error);
                    isVoiceListening = false;
                    voiceButton.textContent = '🎙️';
                    voiceButton.style.backgroundColor = 'var(--primary-color)';
                };
            } else {
                // Tarayıcı desteklemiyorsa butonu gizle
                voiceButton.style.display = 'none';
                alertMessage('Tarayıcınız sesli girişi desteklemiyor. 😥');
            }

            function toggleVoiceInput() {
                if (isVoiceListening) {
                    isVoiceListening = false;
                    recognition.stop();
                    voiceButton.textContent = '🎙️';
                    voiceButton.style.backgroundColor = 'var(--primary-color)';
                    input.focus();
                } else {
                    if (isThinking) {
                        alertMessage('Lütfen botun cevabını bekleyin!');
                        return;
                    }
                    isVoiceListening = true;
                    recognition.start();
                    voiceButton.textContent = '🔴 Dinleniyor...';
                    voiceButton.style.backgroundColor = 'red';
                    input.placeholder = 'Lütfen konuşun...';
                }
            }


            // --- Local Storage ve History Yönetimi ---

            function saveHistory() {
                try {
                    // API'ye gönderilen sistem mesajlarını kaydetme (sadece user/bot)
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
                        
                        history.forEach(msg => {
                            if (msg.role !== 'system') {
                                displayMessage(msg.role, msg.content, false); // Typewriter kapalı
                            }
                        });
                        conversation = history;
                        
                        // Eğer geçmiş boşsa veya ilk karşılama mesajı yoksa ekle
                        if (conversation.length === 0 || conversation[0].role !== 'bot') {
                             displayMessage('bot', initialGreeting, false);
                             conversation.push({role: 'bot', content: initialGreeting});
                             saveHistory();
                        }
                        scrollToBottom();
                    } else {
                        // İlk karşılama mesajını görüntüle ve geçmişe ekle
                        displayMessage('bot', initialGreeting, false);
                        conversation.push({role: 'bot', content: initialGreeting});
                        saveHistory();
                    }
                } catch (e) {
                    console.error("Local storage yüklenirken hata:", e);
                    historyDiv.innerHTML = '';
                    displayMessage('bot', initialGreeting, false);
                    conversation.push({role: 'bot', content: initialGreeting});
                    saveHistory();
                }
            }

            // Sayfa yüklendiğinde geçmişi yükle
            window.onload = loadHistory;

            // --- Mesaj Gönderme ve Görüntüleme ---

            function disableInput(disable) {
                isThinking = disable;
                input.disabled = disable;
                sendButton.disabled = disable;
                if (disable) {
                    sendButton.innerHTML = 'Bekle...';
                    voiceButton.disabled = disable;
                } else {
                    sendButton.innerHTML = 'Gönder';
                    voiceButton.disabled = disable;
                    input.focus(); // İşlem bitince input'a odaklan
                }
            }

            function addTypingIndicator() {
                const indicator = document.createElement('div');
                indicator.id = 'typing-indicator';
                indicator.classList.add('typing-indicator', 'bot');
                indicator.innerHTML = '<div class="spinner"></div> <span>Yazıyor...</span>';
                historyDiv.appendChild(indicator);
                scrollToBottom();
                return indicator;
            }

            function removeTypingIndicator(indicator) {
                if (indicator && indicator.parentNode) {
                    indicator.parentNode.removeChild(indicator);
                }
            }
            
            // YENİ TYPEWRITER FONKSİYONU: HTML etiketlerini atlayıp sadece metin içeriğini yazar
            function typeWriter(element, text) {
                let i = 0;
                element.innerHTML = ''; // İçeriği temizle

                function type() {
                    if (i < text.length) {
                        let char = text[i];

                        if (char === '<') {
                            // HTML tag start: Find the end of the tag
                            const tagEndIndex = text.indexOf('>', i);
                            if (tagEndIndex !== -1) {
                                const tagContent = text.substring(i, tagEndIndex + 1);
                                element.innerHTML += tagContent;
                                i = tagEndIndex + 1; // Skip past the entire tag
                            } else {
                                element.innerHTML += char;
                                i++;
                            }
                        } else if (char === '&') {
                            // HTML entity start (e.g., &nbsp;): Find the semicolon
                            const entityEndIndex = text.indexOf(';', i);
                            if (entityEndIndex !== -1) {
                                const entity = text.substring(i, entityEndIndex + 1);
                                element.innerHTML += entity;
                                i = entityEndIndex + 1; // Skip past the entire entity
                            } else {
                                element.innerHTML += char;
                                i++;
                            }
                        } else {
                            // Normal character: Append one character at a time
                            element.innerHTML += char;
                            i++;
                        }

                        scrollToBottom();
                        setTimeout(type, 15); // Hızlı ve doğal yazım hızı
                    }
                }
                type();
            }

            // GÜNCELLENEN displayMessage FONKSİYONU: Typewriter'a hazır içerik sunar
            function displayMessage(sender, text, useTypewriter = true) {
                const div = document.createElement('div');
                div.classList.add('message', sender);
                
                // Markdown'ı basitçe kalın metne çevir (Markdown parser kullanmadan)
                const formattedText = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

                if (sender === 'user') {
                    div.innerHTML = `<strong style="color: #98c379;">Sen:</strong> ${formattedText}`;
                    historyDiv.appendChild(div);
                } else {
                    // Bot mesajı: Başlık ve içerik span'ı
                    div.innerHTML = `<strong style="color: var(--typing-color);">HyperNova:</strong> <span class="bot-text-content"></span>`;
                    historyDiv.appendChild(div);
                    const contentElement = div.querySelector('.bot-text-content');

                    if (useTypewriter) {
                        // Typewriter kullan, formattedText'i HTML olarak yaz
                        typeWriter(contentElement, formattedText);
                    } else {
                        // History yüklenirken veya anlık mesajlarda direkt HTML olarak yaz
                        contentElement.innerHTML = formattedText;
                    }
                }
                
                scrollToBottom();
                return div;
            }


            function sendMessage() {
                if (isThinking) {
                    alertMessage('Lütfen bekleyin! HyperNova hala düşünüyor... 🧠');
                    return;
                }

                const message = input.value.trim();
                if (!message) return;

                // Kullanıcı mesajını ekle
                displayMessage('user', message, false); // Kullanıcı mesajında typewriter yok
                
                // Konuşma geçmişine ekle
                conversation.push({role: 'user', content: message});
                saveHistory();

                input.value = '';
                disableInput(true); // Input'u ve Gönder butonunu devre dışı bırak
                const typingIndicator = addTypingIndicator(); // "Yazıyor..." göster

                // API'ye gönder (Flask'a POST)
                fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        message: message,
                        history: conversation
                    }) // Tüm geçmişi gönder
                })
                .then(response => response.json())
                .then(data => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    
                    const botResponse = data.response;
                    
                    // Bot mesajını görüntüle (typewriter efektiyle)
                    // GÜNCELLENDİ: displayMessage'in kendi içinde typewriter çağrılıyor.
                    displayMessage('bot', botResponse, true); 
                    
                    // Konuşma geçmişine ekle ve kaydet
                    conversation.push({role: 'bot', content: botResponse});
                    saveHistory();

                })
                .catch(error => {
                    removeTypingIndicator(typingIndicator);
                    disableInput(false);
                    console.error('API İsteği Hatası:', error);
                    alertMessage('Hata: Sunucuya bağlanılamadı veya bir sorun oluştu. Lütfen tekrar deneyin. 😵‍💫');
                });
            }

            // --- Yardımcı Fonksiyonlar ---

            function scrollToBottom() {
                historyDiv.scrollTop = historyDiv.scrollHeight;
            }

            // Kullanıcıya görünür hata mesajı (alert yerine)
            function alertMessage(message) {
                console.warn(message);
                // Burada basit bir modal veya snackbar UI gösterimi eklenebilir.
                // Şimdilik sadece konsol uyarısı.
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
        user_message_raw = data.get('message', '')
        # Frontend'den gelen conversation history
        conversation_history = data.get('history', [])
        
        if not user_message_raw:
            return jsonify({"response": "**Hata**: Boş mesaj göndermeye ne gerek vardı? Cidden mi? 🤔"}), 400

        # 2. Güvenlik: Kullanıcı input'unu sanitize et (XSS saldırılarını önle)
        user_message_clean = bleach.clean(user_message_raw, tags=bleach.sanitizer.ALLOWED_TAGS, attributes=bleach.sanitizer.ALLOWED_ATTRIBUTES)
        
        # 3. Dinamik Model Seçimi
        current_model = MODEL_DEFAULT
        # 'hızlı' veya 'flash' kelimeleri varsa hafif modele geç
        if 'hızlı' in user_message_clean.lower() or 'flash' in user_message_clean.lower():
            current_model = MODEL_LIGHTWEIGHT
            logger.info(f"Kullanıcı talebi üzerine hafif model seçildi: {current_model}")
            
        # 4. Geçmişi ve Mesajı Hazırla
        # Frontend'den gelen geçmişi kullan, sadece 'user' ve 'bot' rolleri tut
        messages_for_api = [
            {"role": msg["role"], "content": bleach.clean(msg["content"], tags=[], attributes={})} 
            for msg in conversation_history 
            if msg["role"] in ["user", "bot"]
        ]
        
        # 5. Loglama (Analytics)
        logger.info(f"[{current_model}] Yeni Chat: '{user_message_clean[:50]}...' (IP: {get_remote_address()})")
        
        # 6. Asenkron API Çağrısı
        bot_response = await async_chat_completion(messages=messages_for_api, model=current_model)
        
        # 7. Cevabı Döndür
        return jsonify({"response": bot_response})

    except APIRequestError as e:
        logger.error(f"API Çağrı Hatası (Tekrar Deneme Başarısız): {e}")
        # API Key'in ayarlı olup olmama durumunu kontrol et
        if "API Key Hatası" in str(e):
             return jsonify({"response": f"**Çok Önemli Hata**: OpenRouter API Anahtarınız (API_KEY) Render'da doğru ayarlanmamış. Lütfen kontrol edin. 🔐"}), 500
        return jsonify({"response": f"**Üzgünüm**, API isteği sırasında bir sorun oluştu veya zaman aşımına uğradı. Bir robot bile bu kadar zorlanmazdı! Tekrar dene. 😥"}), 503
    except Exception as e:
        logger.error(f"Genel Hata: {str(e)}")
        # Rate limit hatası (429) Limiter tarafından otomatik yakalanır.
        return jsonify({"response": f"**Beklenmeyen bir hata** oluştu: {str(e)}. Bu kadar kötü kod yazmamıştım oysa ki. 😨"}), 500

if __name__ == '__main__':
    # Production Ortamı İçin Uyarı:
    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        logger.warning("!!! DİKKAT: API_KEY ortam değişkeni ayarlanmadı. Uygulama çalışmayabilir. !!!")

    # Port ayarı (Render, Heroku vb. için dinamik port desteği)
    port = int(os.environ.get('PORT', 8080))
    
    # Gunicorn/Waitress (Üretim Tavsiyesi):
    # Bu kodu üretimde çalıştırmak için 'gunicorn app:app -w 4 -b 0.0.0.0:8080' gibi bir komut kullanın.
    # Flask'ın dahili sunucusu sadece geliştirme amaçlıdır.
    print(f"\n🚀 HyperNova Flask Sunucusu {port} portunda çalışıyor (Geliştirme Modu).\n")
    app.run(debug=False, host='0.0.0.0', port=port)
