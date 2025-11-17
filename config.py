import os
from datetime import timedelta
from typing import Dict

# Env vars
API_KEY = os.getenv('API_KEY', 'Your API')
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_DEFAULT = "meituan/longcat-flash-chat:free"
DEVELOPER_USERNAME = "yuiouo"
DEVELOPER_PASSWORD = "TheLastGalaxy*"  # Gerçekte hash'le!

# UI Translations
UI_TRANSLATIONS = {
    'en': {
        'register_success': 'Registration successful. You can now log in.',
        # ... (tüm en çevirileri buraya kopyala, kısalttım)
    },
    'tr': {
        'register_success': 'Kayıt başarılı. Şimdi giriş yapabilirsiniz.',
        # ... (tüm tr çevirileri)
    }
}

# System Prompts (EN ve TR)
HYPERNOVA_SYSTEM_PROMPT_CONTENT_EN = (
    "Your name is **HyperNova**. You are an ultra-intelligent AI..."  # Tam prompt
)
# ... (diğer prompt'lar aynı, SYSTEM_PROMPTS_EN/TR dict'leri)

SYSTEM_PROMPTS_EN = {"hypernova": {"role": "system", "content": HYPERNOVA_SYSTEM_PROMPT_CONTENT_EN}, ...}
SYSTEM_PROMPTS_TR = {...}  # Aynı şekilde

DEFAULT_PERSONA = "hypernova"

# Session config
SESSION_LIFETIME = timedelta(days=7)
