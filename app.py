import os
from flask import Flask, request, jsonify, render_template_string
import requests
import logging

# Log ayarları (hata takibi için)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Senin ayarların (API anahtarını buraya koy, ama güvenli tut!)
API_KEY = os.getenv('API_KEY')
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "deepseek/deepseek-chat"

SYSTEM_PROMPT = {
    "role": "system",
    "content": "Sen HyperNova'sın, dostça, yardımcı ve eğlenceli bir AI asistanısın. Kullanıcıyla Türkçe konuş, cevaplarını doğal ve bağlamlı tut. Önceki mesajları hatırla ve konuşmayı derinleştir."
}

# Sohbet geçmişi (her kullanıcı için basit, gerçekte veritabanı kullan)
conversations = {}  # Kullanıcı ID'si ile sakla (şimdilik basit)

@app.route('/')
def index():
    # HTML arayüzü (CSS ve JS ile)
    html_template = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Akıllı Sohbet Asistanı</title>
        <style>
            body { 
                background-color: #16161a; 
                color: #eaeaee; 
                font-family: 'Arial', sans-serif; 
                margin: 0; 
                padding: 20px; 
                display: flex; 
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
            }
            .chat-container { 
                width: 500px; 
                height: 600px; 
                background-color: #1e1e2e; 
                border-radius: 12px; 
                padding: 20px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.5); 
                display: flex; 
                flex-direction: column; 
            }
            .title { 
                text-align: center; 
                font-size: 24px; 
                font-weight: bold; 
                color: white; 
                margin-bottom: 20px; 
                text-shadow: 0 0 10px rgba(99, 102, 241, 0.5); 
            }
            #chat-history { 
                flex: 1; 
                background-color: #232326; 
                border-radius: 8px; 
                padding: 12px; 
                overflow-y: auto; 
                font-size: 14px; 
                line-height: 1.4; 
                margin-bottom: 10px; 
            }
            .message { 
                margin-bottom: 10px; 
                padding: 8px; 
                border-radius: 6px; 
            }
            .user { 
                background-color: #6366f1; 
                color: white; 
                text-align: right; 
            }
            .bot { 
                background-color: #2e2e33; 
                color: #eaeaee; 
            }
            .input-area { 
                display: flex; 
                gap: 10px; 
            }
            #message-input { 
                flex: 1; 
                padding: 10px; 
                border: none; 
                border-radius: 8px; 
                background-color: #2e2e33; 
                color: white; 
                font-size: 14px; 
            }
            #send-button { 
                padding: 10px 20px; 
                background-color: #6366f1; 
                color: white; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer; 
                font-weight: bold; 
            }
            #send-button:hover { 
                background-color: #7c83ff; 
            }
            .typing { 
                color: #7aa2f7; 
                font-style: italic; 
            }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="title">HyperNova AI ✦ Derin Sohbet Modu</div>
            <div id="chat-history">
                <div class="message bot"><strong style="color: #7aa2f7;">HyperNova:</strong> Selam! Ben HyperNova. DeepSeek entegrasyonuyla artık çok daha akıllı cevaplar verebiliyorum. Ne konuşmak istersin?</div>
            </div>
            <div class="input-area">
                <input type="text" id="message-input" placeholder="Bir şey yaz..." onkeypress="if(event.key==='Enter') sendMessage()">
                <button id="send-button" onclick="sendMessage()">Gönder</button>
            </div>
        </div>

        <script>
            let conversation = [];  // Sohbet geçmişi

            function sendMessage() {
                const input = document.getElementById('message-input');
                const message = input.value.trim();
                if (!message) return;

                // Kullanıcı mesajını ekle
                addMessage('user', message);
                input.value = '';

                // API'ye gönder (Flask'a POST)
                fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: message})
                })
                .then(response => response.json())
                .then(data => {
                    addMessage('bot', data.response);
                })
                .catch(error => {
                    addMessage('bot', 'Hata: Bağlantı sorunu!');
                });
            }

            function addMessage(sender, text) {
                const history = document.getElementById('chat-history');
                const div = document.createElement('div');
                div.classList.add('message', sender);
                if (sender === 'user') {
                    div.innerHTML = `<strong style="color: #98c379;">Sen:</strong> ${text}`;
                } else {
                    div.innerHTML = `<strong style="color: #7aa2f7;">HyperNova:</strong> ${text}`;
                }
                history.appendChild(div);
                history.scrollTop = history.scrollHeight;

                // Bot için yavaş yazma efekti
                if (sender === 'bot') {
                    typeWriter(div.querySelector('strong').nextSibling, text);
                }
            }

            function typeWriter(element, text) {
                let i = 0;
                element.textContent = '';  // Temizle
                function type() {
                    if (i < text.length) {
                        element.textContent += text.charAt(i);
                        i++;
                        setTimeout(type, 20);  // 20ms arayla karakter ekle
                    }
                }
                type();
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template)

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data['message']
        
        # Sohbet geçmişini al (basit, her seferinde yeni başla - geliştir)
        conversation = [{"role": "user", "content": user_message}]
        
        # API isteği (senin orijinal kodundan)
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://yourapp.com",
            "X-Title": "HyperNova AI"
        }
        messages = [SYSTEM_PROMPT] + conversation
        payload = {"model": MODEL, "messages": messages, "max_tokens": 500, "temperature": 0.7}
        
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        bot_response = response.json()["choices"][0]["message"]["content"].strip()
        
        return jsonify({"response": bot_response})
    except Exception as e:
        logging.error(f"Hata: {str(e)}")
        return jsonify({"response": f"Hata: {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)