import os
import logging
import bcrypt
from flask import Flask, request, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from database import init_db
from auth import auth_bp
from chat import chat_bp
from admin import admin_bp
from config import UI_TRANSLATIONS, DEVELOPER_USERNAME, DEVELOPER_PASSWORD, DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per hour", "15 per minute"]
)

app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(chat_bp, url_prefix='/api')
app.register_blueprint(admin_bp)

init_db()

# Developer user ekle
from database import get_db_connection
conn = get_db_connection()
with conn.cursor() as cursor:
    cursor.execute("SELECT id FROM users WHERE username = %s", (DEVELOPER_USERNAME,))
    if not cursor.fetchone():
        hashed = bcrypt.hashpw(DEVELOPER_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("""
            INSERT INTO users (username, password, premium_until)
            VALUES (%s, %s, NOW() + INTERVAL '9999 days')
        """, (DEVELOPER_USERNAME, hashed))
        conn.commit()
        logger.info(f"Developer user '{DEVELOPER_USERNAME}' eklendi.")
conn.close()

@app.route('/')
def index():
    lang = request.cookies.get('lang', 'en')
    translations = UI_TRANSLATIONS.get(lang, UI_TRANSLATIONS['en'])
    # TAM ORİJİNAL HTML TEMPLATE (CSS ve JS dahil – orijinal mesajından kopyalandı)
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HyperNova AI ✦ Cosmic Intelligence</title>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
                font-family: 'Montserrat', sans-serif;
                margin: 0;
                padding: 0;
                min-height: 100vh;
                transition: background-color 0.4s ease; /* Tema geçiş animasyonu */
            }
            /* --- Ana Container (YENİ: Sidebar + Chat) --- */
            .main-container {
                display: flex;
                height: 100vh;
                max-width: 100vw;
                overflow: hidden;
            }
            /* Sidebar Stilleri (YENİ: Modern ve Animasyonlu) */
            .sidebar {
                width: 280px;
                background: linear-gradient(180deg, var(--card-bg) 0%, rgba(255,255,255,0.8) 100%);
                border-right: 1px solid var(--border-color);
                padding: 20px 0;
                overflow-y: auto;
                box-shadow: 4px 0 20px var(--shadow-color);
                display: flex;
                flex-direction: column;
                transition: width 0.3s ease;
            }
            .sidebar:hover {
                box-shadow: 4px 0 30px var(--shadow-color);
            }
            .sidebar h3 {
                padding: 0 20px 15px;
                margin: 0;
                color: var(--primary-color);
                font-size: 16px;
                font-weight: 600;
                border-bottom: 1px solid var(--border-color);
                letter-spacing: 0.5px;
            }
            .sidebar-toolbar {
                padding: 0 16px 16px;
                display: flex;
                flex-direction: column;
                gap: 8px;
                border-bottom: 1px solid var(--border-color);
            }
            .new-chat-button, .save-chat-sidebar-button {
                padding: 12px;
                background: linear-gradient(135deg, var(--primary-color), #a78bfa);
                color: white;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Montserrat', sans-serif;
                transition: all 0.3s ease;
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
            }
            .new-chat-button:hover, .save-chat-sidebar-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
            }
            .save-chat-sidebar-button {
                background: linear-gradient(135deg, #10b981, #059669);
                box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            }
            .save-chat-sidebar-button:hover {
                box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
            }
            .saved-chat {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                cursor: pointer;
                border-bottom: 1px solid rgba(209, 213, 219, 0.2);
                transition: all 0.3s ease;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Montserrat', sans-serif;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                position: relative;
                animation: slideInLeft 0.4s ease-out forwards;
            }
            .saved-chat:nth-child(even) {
                background: rgba(209, 213, 219, 0.1);
            }
            .saved-chat:hover {
                background: linear-gradient(90deg, var(--primary-color), #a78bfa);
                color: white;
                transform: translateX(5px);
                box-shadow: 0 4px 12px rgba(99, 102, 241, 0.2);
            }
            .saved-chat.active {
                background: linear-gradient(135deg, var(--primary-color), #a78bfa);
                color: white;
                box-shadow: inset 0 0 0 2px rgba(255,255,255,0.2);
            }
            .saved-chat-name {
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                font-weight: 500;
            }
            .delete-chat-button {
                background: none;
                border: none;
                color: inherit;
                cursor: pointer;
                font-size: 16px;
                padding: 4px 8px;
                border-radius: 50%;
                transition: all 0.2s ease;
                opacity: 0.7;
            }
            .saved-chat:hover .delete-chat-button {
                opacity: 1;
                background: rgba(255,255,255,0.2);
            }
            .delete-chat-button:hover {
                background: rgba(239, 68, 68, 0.3);
                color: #ef4444;
            }
            .save-limit {
                padding: 12px 20px;
                text-align: center;
                font-size: 12px;
                color: var(--text-color);
                opacity: 0.6;
                font-style: italic;
                font-family: 'Montserrat', sans-serif;
            }
            @keyframes slideInLeft {
                from {
                    opacity: 0;
                    transform: translateX(-20px);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }
            /* Chat Container (Güncellendi: Sidebar ile uyumlu) */
            .chat-wrapper {
                flex: 1;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 10px;
            }
            .chat-container {
                width: 100%;
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
                margin: 0; /* Reklamlar kaldırıldı, sidebar için */
            }
          
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
            }
            #theme-toggle, #clear-button, #lang-toggle {
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
            #theme-toggle:hover, #clear-button:hover, #lang-toggle:hover {
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
            /* Input Alanı (Güncellendi: Sohbet Kaydet Butonu Kaldırıldı) */
            .input-area {
                display: flex;
                gap: 10px;
                align-items: center;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
                font-family: 'Montserrat', sans-serif;
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
            @media (max-width: 900px) {
                .main-container {
                    flex-direction: column;
                }
                .sidebar {
                    width: 100%;
                    height: auto;
                    order: 2;
                }
                .chat-wrapper {
                    order: 1;
                }
                .chat-container {
                    height: 70vh;
                }
            }
            @media (max-width: 640px) {
                .chat-container {
                    width: 100%;
                    height: 70vh;
                    padding: 15px;
                    border-radius: 0;
                    box-shadow: none;
                    margin: 0;
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
      
        <div id="authModal" class="modal" onclick="closeModal(event)">
            <div class="modal-content">
                <h3 id="modalTitle">Login</h3>
                <p id="auth-message" style="display: none;"></p>
                <input type="text" id="authUsername" placeholder="Username" required>
                <input type="password" id="authPassword" placeholder="Password" required>
                <button onclick="handleAuth()">Login</button>
                <button style="background-color: #10b981; margin-top: 15px;" onclick="switchAuthMode()">Switch to Register</button>
            </div>
        </div>
      
        <div class="main-container">
            <!-- YENİ: Sidebar -->
            <div class="sidebar" id="sidebar">
                <div class="sidebar-toolbar">
                    <button class="new-chat-button" onclick="newConversation()">New Chat</button>
                    <button id="save-chat-sidebar-button" class="save-chat-sidebar-button" onclick="saveCurrentConversation()">💾 Save Chat</button>
                </div>
                <h3>Saved Chats</h3>
                <div id="saved-chats-list"></div>
                <div class="save-limit">Maximum 5 chats</div>
            </div>
            <div class="chat-wrapper">
                <div class="chat-container">
                    <div class="header">
                        <div class="title">HyperNova AI 🪐✨</div>
                        <div class="header-buttons">
                            <button id="clear-button" onclick="clearConversation()" title="Clear and Reset Conversation">🧹</button>
                            <button id="theme-toggle" onclick="toggleTheme()" title="Change Theme">☀️</button>
                            <button id="lang-toggle" onclick="toggleLanguage()" title="Change Language">EN</button>
                        </div>
                    </div>
                  
                    <div id="auth-status">
                        <span id="user-info">Not Logged In</span>
                        <div id="auth-buttons">
                            <button onclick="showModal('login')">Login</button>
                            <button onclick="showModal('register')">Register</button>
                            <button id="logout-button" style="display: none;" onclick="logout()">Logout</button>
                        </div>
                    </div>
                  
                    <select id="persona-select" onchange="changePersona()">
                        <option value="hypernova">HyperNova (Standard) 🪐</option>
                        <option value="kaia" disabled>Kaia (Anime) (Premium) 🌠</option>
                        <option value="hypernova_dengesiz">HyperNova Chaotic (Chaotic) 🌪️</option>
                    </select>
                    <div id="chat-history">
                    </div>
                  
                    <div class="input-area">
                        <input type="text" id="message-input" placeholder="Ask a cosmic question..." onkeypress="if(event.key==='Enter') sendMessage()">
                        <button id="voice-button" class="action-button" onclick="toggleVoiceInput()" title="Voice Input">🎙️</button>
                        <button id="send-button" class="action-button" onclick="sendMessage()">Send</button>
                    </div>
                </div>
            </div>
        </div>
        <script>
            let conversation = [];
            let isThinking = false;
            let isVoiceListening = false;
            let savedConversations = []; // Kaydedilen sohbetler dizisi (API'den yüklenir)
            let currentLoadedChatId = null; // Aktif yüklenen sohbet ID'si
            let isCurrentSaved = false; // Mevcut sohbet kaydedildi mi?
          
            const historyDiv = document.getElementById('chat-history');
            const input = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');
            const voiceButton = document.getElementById('voice-button');
            const themeToggle = document.getElementById('theme-toggle');
            const clearButton = document.getElementById('clear-button');
            const personaSelect = document.getElementById('persona-select');
            const kaiaOption = personaSelect.querySelector('option[value="kaia"]');
            const sidebar = document.getElementById('sidebar');
            const savedChatsList = document.getElementById('saved-chats-list');
            // --- YENİ AUTH DEĞİŞKENLERİ ---
            let isLoggedIn = false;
            let isPremium = false;
            let currentUsername = null;
            let authMode = 'login'; // login veya register
            let currentLang = localStorage.getItem('lang') || 'en';
            // --- ÇEVİRİLER ---
            const TRANSLATIONS = {{ translations | tojson }};
            // --- Başlangıç Değerleri (Karaktere göre değişecek) ---
            const GREETINGS = {
                en: {
                    hypernova: {
                        text: "**HyperNova** is here. I am an artificial intelligence with access to the universal database. 🌌 Clearly state what you want to learn. I focus on conveying accurate and correct information. ✨",
                        title: "HyperNova AI 🪐✨",
                        placeholder: "Ask a cosmic question..."
                    },
                    kaia: {
                        text: "**Kaia** with you! 💖 How are you today? You can ask me anything, I'll answer in the sweetest way! Shall we start right away? 🌸",
                        title: "Kaia AI 💖🌸",
                        placeholder: "Say something sweet to Kaia..."
                    },
                    hypernova_dengesiz: {
                        text: "**HyperNova Chaotic** here, the lord of chaos! 🌪️ Tell me whatever shitty thing you want, I'll answer without judging (maybe a little). Are you ready, idiot? 💥",
                        title: "HyperNova Chaotic 🌪️💥",
                        placeholder: "Ask a chaotic question..."
                    }
                },
                tr: {
                    hypernova: {
                        text: "**HyperNova** burada. Evrensel veri tabanına erişimi olan yapay zekayım. 🌌 Ne öğrenmek istediğini açıkça belirt. Kesin ve doğru bilgi aktarmaya odaklıyım. ✨",
                        title: "HyperNova AI 🪐✨",
                        placeholder: "Kozmik bir soru sor..."
                    },
                    kaia: {
                        text: "**Kaia** seninle! 💖 Bugün nasılsın? Bana her şeyi sorabilirsin, sana en tatlı şekilde cevap vereceğim! Hemen başlayalım mı? 🌸",
                        title: "Kaia AI 💖🌸",
                        placeholder: "Kaia'ya tatlı bir şey söyle..."
                    },
                    hypernova_dengesiz: {
                        text: "**HyperNova Dengesiz** burada, kaosun efendisi! 🌪️ Ne boktan bir şey istersen söyle, seni yargılamadan (belki biraz) cevap veririm. Hazır mısın aptal? 💥",
                        title: "HyperNova Dengesiz 🌪️💥",
                        placeholder: "Dengesiz bir soru sor..."
                    }
                }
            };
            let currentPersona = localStorage.getItem('current_persona') || 'hypernova';
            let currentTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
            // --- Markdown Parser (YENİ: Kalın ve italik için basit parser) ---
            function parseMarkdown(text) {
                // **kalın** -> <strong>kalın</strong>
                text = text.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                // *italik* -> <em>italik</em>
                text = text.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
                // [metin](url) -> <a href="url">metin</a>
                text = text.replace(/\\[(.*?)\\]\\((.*?)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                return text;
            }
            function getPersonaDesc(persona) {
                return TRANSLATIONS[currentLang][`desc_${persona}`];
            }
            function getPersonaName(persona) {
                return TRANSLATIONS[currentLang][`name_${persona}`];
            }
            function toggleLanguage() {
                currentLang = currentLang === 'en' ? 'tr' : 'en';
                localStorage.setItem('lang', currentLang);
                document.cookie = `lang=${currentLang}; max-age=${7*24*60*60}; path=/`;
                updateLanguage();
                updateUIForPersona();
            }
            function updateLanguage() {
                const t = TRANSLATIONS[currentLang];
                // Sidebar
                document.querySelector('.new-chat-button').textContent = t.newChat;
                document.getElementById('save-chat-sidebar-button').textContent = t.saveChat;
                document.querySelector('.sidebar h3').textContent = t.savedChats;
                document.querySelector('.save-limit').textContent = t.maxChats;
                // Buttons
                document.getElementById('send-button').textContent = t.send;
                document.getElementById('clear-button').title = t.clearTitle;
                document.getElementById('theme-toggle').title = t.themeTitle;
                document.getElementById('voice-button').title = t.voiceTitle;
                document.getElementById('lang-toggle').title = t.langTitle;
                document.getElementById('lang-toggle').textContent = currentLang.toUpperCase();
                // Persona select
                const kaiaDisabled = isPremium ? '' : 'disabled';
                const selectedHyper = currentPersona === 'hypernova' ? 'selected' : '';
                const selectedDeng = currentPersona === 'hypernova_dengesiz' ? 'selected' : '';
                personaSelect.innerHTML = `
                    <option value="hypernova" ${selectedHyper}>${t.persona.hypernova}</option>
                    <option value="kaia" ${kaiaDisabled}>${t.persona.kaia}</option>
                    <option value="hypernova_dengesiz" ${selectedDeng}>${t.persona.hypernova_dengesiz}</option>
                `;
                personaSelect.value = currentPersona;
                // Title
                document.title = currentLang === 'en' ? 'HyperNova AI ✦ Cosmic Intelligence' : 'HyperNova AI ✦ Kozmik Zeka';
                document.documentElement.lang = currentLang;
            }
            // --- API İLE SOHBET FONKSİYONLARI (YENİ) ---
            async function saveCurrentConversation() {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqSave);
                    return;
                }
                if (conversation.length < 2) { // En az bir mesaj çifti olmalı
                    alertMessage(t.saveMinMsg);
                    return;
                }
                const chatName = prompt(t.savePrompt);
                if (!chatName || chatName.trim() === '') {
                    alertMessage(t.saveNoName);
                    return;
                }
                // Maksimum 5 sohbet kontrolü (API'den)
                const userChats = await loadUserChats();
                if (userChats.chats.length >= 5) {
                    alertMessage(t.saveMax);
                    return;
                }
                try {
                    const response = await fetch('/api/save_chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: chatName.trim(), messages: conversation })
                    });
                    const data = await response.json();
                    if (response.ok) {
                        isCurrentSaved = true;
                        currentLoadedChatId = data.chat_id;
                        await loadUserChats(); // Listeyi güncelle
                        alertMessage(`${t.saved}"${chatName.trim()}"${t.savedMsg}`);
                    } else {
                        alertMessage(`${t.saveError}${data.error}`);
                    }
                } catch (error) {
                    alertMessage(t.networkError);
                }
            }
            async function loadUserChats() {
                const t = TRANSLATIONS[currentLang];
                try {
                    const response = await fetch('/api/load_chats');
                    const data = await response.json();
                    if (response.ok) {
                        savedConversations = data.chats;
                        updateSavedChatsList();
                        return data;
                    } else {
                        alertMessage(`${t.chatsLoadError}${data.error}`);
                    }
                } catch (error) {
                    console.error('Sohbet yükleme hatası:', error);
                }
                savedConversations = [];
                updateSavedChatsList();
                return { chats: [] };
            }
            async function loadSavedConversation(chatId) {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqLoad);
                    return;
                }
                try {
                    const response = await fetch(`/api/load_chat/${chatId}`);
                    const data = await response.json();
                    if (response.ok) {
                        const chat = data.chat;
                        conversation = chat.messages;
                        historyDiv.innerHTML = '';
                        conversation.forEach(msg => {
                            if (msg.role !== 'system') {
                                displayMessage(msg.role, msg.content, false);
                            }
                        });
                        scrollToBottom();
                        // Aktif sohbeti vurgula
                        currentLoadedChatId = chatId;
                        isCurrentSaved = true;
                        updateSavedChatsList();
                        alertMessage(`"${chat.name}"${t.loaded}`);
                    } else {
                        alertMessage(`${t.loadError}${data.error}`);
                        if (data.error.includes('not found') || data.error.includes('bulunamadı')) {
                            // Silinmişse listeden kaldır
                            await deleteSavedConversation(chatId);
                        }
                    }
                } catch (error) {
                    alertMessage(t.networkError);
                }
            }
            async function deleteSavedConversation(chatId, event) {
                const t = TRANSLATIONS[currentLang];
                if (!isLoggedIn) {
                    alertMessage(t.authReqDelete);
                    return;
                }
                event.stopPropagation(); // Tıklama yayılmasını engelle
                if (confirm(t.deleteConfirm)) {
                    try {
                        const response = await fetch(`/api/delete_chat/${chatId}`, { method: 'DELETE' });
                        const data = await response.json();
                        if (response.ok) {
                            if (currentLoadedChatId === chatId) {
                                currentLoadedChatId = null;
                                isCurrentSaved = false;
                                newConversation(); // Aktifse yeni sohbet başlat
                            }
                            await loadUserChats(); // Listeyi güncelle
                            alertMessage(t.deleted);
                        } else {
                            alertMessage(`${t.deleteError}${data.error}`);
                        }
                    } catch (error) {
                        alertMessage(t.networkError);
                    }
                }
            }
            function updateSavedChatsList() {
                savedChatsList.innerHTML = '';
                savedConversations.forEach((chat, index) => {
                    const chatElement = document.createElement('div');
                    chatElement.className = 'saved-chat';
                    chatElement.style.animationDelay = `${index * 0.1}s`;
                    if (currentLoadedChatId === chat.id) {
                        chatElement.classList.add('active');
                    }
                    chatElement.innerHTML = `
                        <span class="saved-chat-name" onclick="loadSavedConversation('${chat.id}')">${chat.name}</span>
                        <button class="delete-chat-button" onclick="deleteSavedConversation('${chat.id}', event)" title="Delete Conversation">🗑️</button>
                    `;
                    savedChatsList.appendChild(chatElement);
                });
            }
            // --- YENİ: Yeni Sohbet Butonu (Kaydedilmişse Sorma) ---
            function newConversation() {
                const t = TRANSLATIONS[currentLang];
                if (isThinking) {
                    alertMessage(t.thinkingNew);
                    return;
                }
                let needsSave = !isCurrentSaved && conversation.length >= 2;
                if (needsSave && confirm(t.newConvSaveConfirm)) {
                    saveCurrentConversation();
                } else if (needsSave && !confirm(t.discardConfirm)) {
                    return; // Vazgeç
                }
                clearConversation(true); // Sessiz temizle
                currentLoadedChatId = null; // Aktif sohbeti sıfırla
                isCurrentSaved = false;
                updateSavedChatsList(); // Aktif vurguyu kaldır
                alertMessage(t.newConvStarted);
            }
            // --- AUTH FONKSİYONLARI (YENİ) ---
          
            function showModal(mode) {
                const t = TRANSLATIONS[currentLang];
                authMode = mode;
                document.getElementById('modalTitle').textContent = mode === 'login' ? t.modalLogin : t.modalRegister;
                document.querySelector('.modal-content button:first-of-type').textContent = mode === 'login' ? t.login : t.register;
                document.querySelector('.modal-content button:last-of-type').textContent = mode === 'login' ? t.switchRegister : t.switchLogin;
                document.getElementById('authUsername').placeholder = t.usernamePH;
                document.getElementById('authPassword').placeholder = t.passwordPH;
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
                const t = TRANSLATIONS[currentLang];
                const username = document.getElementById('authUsername').value.trim();
                const password = document.getElementById('authPassword').value;
                const messageElement = document.getElementById('auth-message');
              
                messageElement.style.display = 'none';
              
                if (!username || !password) {
                    messageElement.textContent = t.emptyCred;
                    messageElement.style.display = 'block';
                    return;
                }
              
                const endpoint = authMode === 'login' ? '/api/login' : '/api/register';
              
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
                            await loadUserChats(); // Sohbetleri yükle
                            const welcomeMsg = `${t.welcome}${currentUsername}! ${isPremium ? t.welcomePremium : t.welcomeFree}`;
                            alertMessage(welcomeMsg);
                        } else {
                             // Kayıt başarılıysa, Giriş moduna geç
                            switchAuthMode();
                        }
                    } else {
                        messageElement.textContent = `Error: ${data.error}`;
                        messageElement.style.color = '#ef4444';
                        messageElement.style.display = 'block';
                    }
                  
                } catch (error) {
                    messageElement.textContent = t.networkError;
                    messageElement.style.color = '#ef4444';
                    messageElement.style.display = 'block';
                }
            }
          
            async function logout() {
                try {
                    const response = await fetch('/api/logout', { method: 'POST' });
                    if (response.ok) {
                        await checkAuthStatus();
                        savedConversations = []; // Sohbetleri temizle
                        updateSavedChatsList();
                        alertMessage(TRANSLATIONS[currentLang].logout); // backend message
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
                    const response = await fetch('/api/is_premium');
                    const data = await response.json();
                  
                    isLoggedIn = data.logged_in;
                    currentUsername = data.username;
                    isPremium = data.is_premium;
                  
                    const t = TRANSLATIONS[currentLang];
                    const authStatusDiv = document.getElementById('auth-status');
                    const userInfoSpan = document.getElementById('user-info');
                    const authButtonsDiv = document.getElementById('auth-buttons');
                  
                    if (isLoggedIn) {
                        // Giriş yapmış
                        authButtonsDiv.innerHTML = `<button id="logout-button" onclick="logout()">${t.logout}</button>`;
                      
                        let premiumInfo = '';
                        if (isPremium) {
                            premiumInfo = `<span class="premium-tag" title="Bitiş: ${data.premium_until}">⭐ PREMIUM</span>`;
                        }
                      
                        userInfoSpan.innerHTML = `${t.welcome}<strong>${currentUsername}</strong>${premiumInfo}`;
                    } else {
                        // Giriş yapmamış
                        userInfoSpan.innerHTML = t.notLoggedIn;
                        authButtonsDiv.innerHTML = `
                            <button onclick="showModal('login')">${t.login}</button>
                            <button onclick="showModal('register')">${t.register}</button>
                        `;
                        isPremium = false;
                        savedConversations = [];
                        updateSavedChatsList();
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
                const t = TRANSLATIONS[currentLang];
                const persona = currentPersona;
                const greeting = GREETINGS[currentLang][persona];
                const titleElement = document.querySelector('.title');
                titleElement.textContent = greeting.title;
                input.placeholder = greeting.placeholder;
              
                // Tema güncellemesi
                applyTheme(currentTheme);
                // Select kutusunu doğru değere ayarla (Yüklemede gerekebilir)
                personaSelect.value = persona;
              
                // Kaia seçiliyse ve premium değilse zorla değiştir
                if (persona === 'kaia' && !isPremium) {
                    alertMessage(t.kaiaPremiumReq);
                    currentPersona = 'hypernova';
                    localStorage.setItem('current_persona', 'hypernova');
                    updateUIForPersona();
                    return;
                }
            }
            function changePersona() {
                const t = TRANSLATIONS[currentLang];
                const newPersona = personaSelect.value;
              
                if (newPersona === 'kaia' && !isPremium) {
                    alertMessage(t.kaiaPremiumReq);
                    // Seçimi HyperNova'ya geri döndür
                    personaSelect.value = currentPersona;
                    return;
                }
              
                if (newPersona !== currentPersona) {
                    const desc = getPersonaDesc(newPersona);
                    const confirmMsg = t.changeConfirm.replace('%s', desc) + t.historyWillClear + '. ' + t.sure + '?';
                    if (confirm(confirmMsg)) {
                        currentPersona = newPersona;
                        localStorage.setItem('current_persona', newPersona);
                        clearConversation(true); // Geçmişi sil ve yeniden yükle
                        updateUIForPersona();
                        const name = getPersonaName(newPersona);
                        alertMessage(t.modeChangedTo + name + t.newChatStarted);
                    } else {
                        // Vazgeçilirse select kutusunu geri ayarla
                        personaSelect.value = currentPersona;
                    }
                }
            }
            // --- Konuşmayı Temizle (Güncellendi: Kaydedilen sohbetleri etkilemez) ---
            function clearConversation(isSilent = false) {
                const t = TRANSLATIONS[currentLang];
                if (isThinking) {
                    if (!isSilent) alertMessage(t.thinkingClear);
                    return;
                }
              
                if (isSilent || confirm(t.clearConfirm)) {
                    conversation = [];
                    historyDiv.innerHTML = '';
                    displayInitialGreeting();
                    currentLoadedChatId = null;
                    isCurrentSaved = false;
                    updateSavedChatsList();
                    if (!isSilent) alertMessage(t.cleared);
                }
            }
            function displayInitialGreeting() {
                const greetingText = GREETINGS[currentLang][currentPersona].text;
                displayMessage('bot', greetingText, false);
                conversation = [{role: 'bot', content: greetingText}];
                isCurrentSaved = false;
            }
            // --- Mesaj Gönderme (GÜNCELLENDİ) ---
            async function sendMessage() {
                const t = TRANSLATIONS[currentLang];
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
                    const apiMessages = conversation.map(msg => ({ role: msg.role, content: msg.content }));
                  
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ messages: apiMessages, persona: currentPersona, lang: currentLang }),
                    });
                    removeTypingIndicator(typingIndicator);
                  
                    if (response.status === 403) {
                         // Premium kısıtlaması (Kaia modu)
                         const errorData = await response.json();
                         const errorMessage = errorData.error;
                         displayMessage('bot', `${t.errorPrefix}${errorMessage}`, true);
                       
                         // Premium gerektiren moddan ücretsiz moda geçişi zorla
                         if (errorData.force_persona === 'hypernova' && currentPersona === 'kaia') {
                              currentPersona = 'hypernova';
                              localStorage.setItem('current_persona', 'hypernova');
                              updateUIForPersona();
                              clearConversation(true);
                              alertMessage(t.kaiaForce);
                         }
                       
                    } else if (!response.ok) {
                        const errorData = await response.json();
                        displayMessage('bot', `${t.errorPrefix}${t.aiConnectFailed}(${errorData.error || t.unknownError})`, true);
                    } else {
                        const data = await response.json();
                        const botResponse = data.response;
                        displayMessage('bot', botResponse, true);
                      
                        // Konuşma geçmişine bot mesajını ekle
                        conversation.push({ role: 'assistant', content: botResponse });
                        isCurrentSaved = false; // Yeni mesaj eklenince kaydedilmemiş say
                    }
                } catch (error) {
                    console.error('Fetch Hatası:', error);
                    removeTypingIndicator(typingIndicator);
                    displayMessage('bot', t.serverError, true);
                } finally {
                    isThinking = false;
                    setControlsDisabled(false);
                }
            }
            // --- Diğer Yardımcı Fonksiyonlar (Aynı Kaldı) ---
            function displayMessage(role, content, scrollTo=true) {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                // Markdown desteği için innerHTML kullanıldı (güvenlik için sanitize edilmeli ama bu demoda değil)
                messageDiv.innerHTML = parseMarkdown(content); // YENİ: Markdown parse et
                historyDiv.appendChild(messageDiv);
                if (scrollTo) {
                    scrollToBottom();
                }
            }
          
            function displayTypingIndicator() {
                const typingDiv = document.createElement('div');
                typingDiv.className = 'message bot typing-indicator';
                typingDiv.innerHTML = `
                    <span>Typing...</span>
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
                 if (!document.querySelector('style[data-alert]')) {
                     style.setAttribute('data-alert', 'true');
                     document.head.appendChild(style);
                 }
            }
          
            function toggleVoiceInput() {
                const t = TRANSLATIONS[currentLang];
                alertMessage(t.voiceDisabled);
            }
          
            // Sayfa Yüklendiğinde
            document.addEventListener('DOMContentLoaded', async () => {
                await loadUserChats(); // Kaydedilen sohbetleri yükle (giriş yapmadan boş)
                await checkAuthStatus(); // Premium ve auth kontrolü
                updateLanguage();
                updateUIForPersona(); // Persona UI güncelle
                displayInitialGreeting(); // İlk mesajı göster
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
    return render_template_string(html_template, lang=lang, translations=translations)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
