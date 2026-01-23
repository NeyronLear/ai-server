"""Файл для запуска сервера модели ИИ с и облачным туннелем."""

import os
import sys
import json
import asyncio
import subprocess
import shutil
from typing import Optional, Dict, Any
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

try:
    from unsloth import FastVisionModel
    from transformers import TextIteratorStreamer
    from threading import Thread
except ImportError:
    print("Внимание: Необходимо установить пакет 'unsloth' для работы")
    FastVisionModel = None

# Configuration
MODEL_PATH = "lora_model"  # Путь к предобученной модели LoRA
BASE_MODEL = "unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit"  # Базовая модель как запасной вариант
PORT = 8000
HOST = "0.0.0.0"

# Global variables
app = FastAPI(title="Сервер ИИ", version="1.0.0")
model = None
tokenizer = None
device = "cuda" if torch.cuda.is_available() else "cpu"

# CORS middleware to allow requests from web interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    max_new_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    do_sample: Optional[bool] = True
    system_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    status: str = "success"


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    gpu_available: bool
    gpu_name: Optional[str] = None


def ensure_cloudflared():
    """Убедиться, что cloudflared установлен и доступен."""
    if shutil.which("cloudflared") is not None:
        return True
    
    print("Cloudflared не найден в. Он необходим для создания туннеля. Скачать можно здесь::")
    print("  Windows: Скачать с https://github.com/cloudflare/cloudflared/releases")
    print("           Или запустить в cmd: winget install --id Cloudflare.cloudflared")
    print("  Linux/Mac: brew install cloudflared")
    return False


def load_model():
    """Загрузка модели ИИ."""
    global model, tokenizer
    
    if FastVisionModel is None:
        raise RuntimeError("Пакет 'unsloth' не установлен. Для начала установите его.")
    
    print(f"Устройство: {device}")
    
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} ГБ")
    
    try:
        # Для начала попробуем загрузить LoRA модель
        if os.path.exists(MODEL_PATH) and os.path.isdir(MODEL_PATH):
            print(f"Загрузка модели из {MODEL_PATH}...")
            model, tokenizer = FastVisionModel.from_pretrained(
                MODEL_PATH,
                load_in_4bit=True,
                use_gradient_checkpointing="unsloth",
            )
            print("Модель LoRA загружена.")
        else:
            # В ином случае загружаем базовую модель
            print(f"Загрузка базовой модели: {BASE_MODEL}...")
            model, tokenizer = FastVisionModel.from_pretrained(
                BASE_MODEL,
                load_in_4bit=True,
                use_gradient_checkpointing="unsloth",
            )
            print("Базовая модель загружена.")
        
        # Установка модели в режим инференса
        FastVisionModel.for_inference(model)

        print("Модель загружена успешно!")
        return True
        
    except Exception as e:
        print(f"Ошибка при загрузке модели: {e}")
        raise


def generate_response(
    message: str,
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    top_p: float = 0.9,
    do_sample: bool = True,
    system_prompt: Optional[str] = None,
) -> str:
    """Генерация ответа от модели ИИ."""
    global model, tokenizer
    
    if model is None or tokenizer is None:
        raise RuntimeError("Модель не загружена.")
    
    try:
        # Форматирование сообщения с учетом системного промпта
        # Если модель не поддерживает системные сообщения, они будут проигнорированы
        if system_prompt and system_prompt.strip():
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
        else:
            # Без системного промта
            messages = [
                {"role": "user", "content": message}
            ]
        
        # Применение макета токенизатора к сообщениям
        try:
            inputs = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt"
            ).to(device)
        except Exception as e:
            # Если модель не поддерживает системные сообщения, объединяем их с сообщением пользователя
            if system_prompt and system_prompt.strip() and len(messages) > 1:
                print(f"Системное сообщение не поддерживается, объединяем с сообщением пользователя: {e}")
                messages = [
                    {"role": "user", "content": f"{system_prompt}\n\n{message}"}
                ]
                inputs = tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_tensors="pt"
                ).to(device)
            else:
                raise
        
        # Генерация ответа
        with torch.no_grad():
            outputs = model.generate(
                inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=do_sample,
                pad_token_id=tokenizer.eos_token_id,
            )
        
        # Декодирование ответа
        response = tokenizer.decode(
            outputs[0][inputs.shape[1]:],
            skip_special_tokens=True
        )
        
        return response.strip()
        
    except Exception as e:
        print(f"Ошибка при генерации ответа: {e}")
        raise


@app.on_event("startup")
async def startup_event():
    """Загрузка модели при запуске сервера."""
    try:
        load_model()
    except Exception as e:
        print(f"Ошибка при загрузке модели: {e}")
        print("Сервер запуститься, но /chat endpoint не будет работать.")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Проверка состояния сервера."""
    gpu_available = torch.cuda.is_available()
    gpu_name = None
    
    if gpu_available:
        gpu_name = torch.cuda.get_device_name(0)
    
    return HealthResponse(
        status="healthy" if model is not None else "model_not_loaded",
        model_loaded=model is not None,
        device=device,
        gpu_available=gpu_available,
        gpu_name=gpu_name,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Эндпоинт чата - основной API для взаимодействия с ИИ."""
    if model is None or tokenizer is None:
        raise HTTPException(
            status_code=503,
            detail="Модель не загружена. Проверьте логи сервера."
        )
    
    if not request.message or not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Сообщение не может быть пустым."
        )
    
    # Validate parameters
    if request.temperature is not None:
        if request.temperature < 0 or request.temperature > 2:
            raise HTTPException(
                status_code=400,
                detail="Температура должна быть между 0 и 2"
            )
    
    if request.top_p is not None:
        if request.top_p < 0 or request.top_p > 1:
            raise HTTPException(
                status_code=400,
                detail="Top_p должен быть между 0 и 1"
            )
    
    try:
        response_text = generate_response(
            message=request.message,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            do_sample=request.do_sample,
            system_prompt=request.system_prompt,
        )
        
        return ChatResponse(
            response=response_text,
            status="success"
        )
        
    except Exception as e:
        print(f"Ошибка в эндпоинте чата: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при генерации ответа: {str(e)}"
        )


@app.get("/")
async def root():
    """Корневой эндпоинт с информацией об API."""
    return {
        "name": "Сервер ИИ",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "chat": "/chat (POST)",
        },
        "model_loaded": model is not None,
    }


def start_cloudflare_tunnel(port: int):
    """Запуск Cloudflare tunnel в отдельном процессе."""
    if not ensure_cloudflared():
        print("Cloudflared не доступен. Сервер будет доступен только локально.")
        return None
    
    try:
        import time
        import threading
        
        # Запуск туннеля
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Функция для чтения URL туннеля из вывода
        def read_tunnel_url():
            time.sleep(3)  # Небольшая задержка для инициализации
            print("\n" + "="*50)
            print("Туннель запускается...")
            print("="*50)
            print("Чтение URL туннеля (это может занять несколько секунд)...")
            
            # Чтение вывода посторочно
            url_found = False
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                if 'https://' in line and '.trycloudflare.com' in line:
                    import re
                    urls = re.findall(r'https://[^\s]+\.trycloudflare\.com', line)
                    if urls:
                        print(f"Публичный URL: {urls[0]}")
                        print("Теперь вы можете использовать этот URL для доступа к вашему серверу ИИ.")
                        url_found = True
                        break
                elif 'trycloudflare.com' in line:
                    print(f"Публичный URL: {line}")
            
            if not url_found:
                print("Не удалось найти URL туннеля в выводе.")
                print("Проверьте вывод cloudflared для самостоятельного поиска URL.")
            print("="*50 + "\n")
        
        thread = threading.Thread(target=read_tunnel_url, daemon=True)
        thread.start()
        
        return process
        
    except Exception as e:
        print(f"Ошибка при запуске Cloudflare tunnel: {e}")
        print("Вы можете вручную запустить туннель с помощью:")
        print(f"cloudflared tunnel --url http://localhost:{port}")
        return None


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Сервер ИИ с Cloudflare tunnel")
    parser.add_argument("--port", type=int, default=PORT, help="Порт сервера")
    parser.add_argument("--host", type=str, default=HOST, help="Хост сервера")
    parser.add_argument("--model-path", type=str, default=MODEL_PATH, help="Путь к модели")
    parser.add_argument("--no-tunnel", action="store_true", help="Не запускать Cloudflare tunnel")
    parser.add_argument("--reload", action="store_true", help="Включить автоматическую перезагрузку при изменениях кода (позволяет видеть изменения без перезапуска сервера)")
    
    args = parser.parse_args()
    
    PORT = args.port
    HOST = args.host
    MODEL_PATH = args.model_path
    
    tunnel_process = None
    if not args.no_tunnel:
        tunnel_process = start_cloudflare_tunnel(PORT)
    
    print(f"\nЗапуск сервера ИИ на {HOST}:{PORT}")
    print(f"Путь к модели: {MODEL_PATH}")
    print(f"Локальный URL: http://localhost:{PORT}")
    print(f"Проверка состояния: http://localhost:{PORT}/health")
    print(f"Эндпоинт чата: http://localhost:{PORT}/chat\n")
    
    try:
        # Запуск сервера Uvicorn
        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            reload=args.reload,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\nВыключение сервера...")
        if tunnel_process:
            tunnel_process.terminate()
        sys.exit(0)
