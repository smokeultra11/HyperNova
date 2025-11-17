import asyncio
import aiohttp
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from flask import request
import bleach
import logging
from config import API_KEY, API_URL, MODEL_DEFAULT, get_system_prompts

logger = logging.getLogger(__name__)

class APIRequestError(Exception):
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIRequestError),
    before_sleep=lambda retry_state: logger.warning(f"API retry {retry_state.attempt_number}"),
    reraise=True
)
async def async_chat_completion(messages: list, model: str, persona: str, lang: str, timeout: int = 90) -> str:
    system_prompts = get_system_prompts(lang)
    system_prompt = system_prompts.get(persona, system_prompts['hypernova'])
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
    if not API_KEY or API_KEY == 'Your API':
        raise APIRequestError("API Key Hatası")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(API_URL, json=payload, headers=headers, timeout=timeout) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise APIRequestError(f"HTTP {response.status}: {error_text[:100]}")
                data = await response.json()
                return data["choices"][0]["message"]["content"].strip()
        except asyncio.TimeoutError:
            raise APIRequestError("Zaman aşımı")
        except Exception as e:
            raise APIRequestError(str(e))
