"""FastAPI сервер для хостинга модели ии с поддержкой туннеля Cloudflare.

Примеры использования:
    python ai_server_cf.py --model-path "./lora_model" --port 8000
    python ai_server_cf.py --base-model "unsloth/Qwen3-8B-unsloth-bnb-4bit"
    python ai_server_cf.py --no-tunnel

Параметры командной строки:
    --host - адрес хоста для запуска сервера (0.0.0.0 по умолчанию)
    --port <int> - номер порта для запуска сервера (8000 по умолчанию)
    --model-path <str> - путь к модели ии (./lora_model по умолчанию)
    --base-model <str> - название запасной модели, если путь основной отсутствует (Qwen/Qwen3-VL-8B-Thinking по умолчанию)
    --load-in-4bit <bool> - загрузка в 4-ех битной квантизации для оптимизации (false по умолчанию)
    --no-tunnel <bool> - отключение запуска туннеля cloudflare
    --reload <bool> - включает перезагрузку uvicorn
"""

import argparse
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional
import logging

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# ---------- Request / response ----------
class ChatRequest(BaseModel):
    message: str = Field(default="", description="Сообщение пользователя")
    max_new_tokens: int = Field(default=512, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    do_sample: bool = True
    system_prompt: Optional[str] = None
    images: Optional[list[str]] = None
    username: Optional[str] = Field(default="Пользователь", description="Имя пользователя")
    session_id: Optional[str] = Field(default="default", description="ID сессии чата")


class ChatResponse(BaseModel):
    response: str
    status: str = "success"


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    device: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    tunnel_url: Optional[str] = None


# ---------- Global runtime state ----------
@dataclass # автоматически создают __init__ для класса, в котором инициализирует данные. по сути генератор шаблона на лету
class RuntimeState:
    model: Optional[object] = None
    tokenizer: Optional[object] = None
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    tunnel_url: Optional[str] = None
    tunnel_process: Optional[subprocess.Popen] = None # Popen создает дочернюю программу в новом процессе
    db_path: str = "chat_history.db"


STATE = RuntimeState()


# ---------- FastAPI app ----------
app = FastAPI(title="AI Server", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Chat history database ----------
def init_chat_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn: # conn — есть соединение с нашей бд
        conn.execute( # ввод команды — есть передача команды в sql
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                generation_settings TEXT
            )
            """
        )
        conn.commit() # исполняем введенную команду


def save_chat_message(
    db_path: str,
    username: str,
    session_id: str,
    user_message: str,
    ai_response: str,
    generation_settings: dict[str, Any],
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_history (
                timestamp,
                username,
                session_id,
                user_message,
                ai_response,
                generation_settings
            ) VALUES (?, ?, ?, ?, ?, ?)
            """, # ? — есть значение, подставляемое в команду из второго параметра execute()
            (
                datetime.now().isoformat(timespec="seconds") + "Z",
                username or "Пользователь",
                session_id or "default",
                user_message,
                ai_response,
                json.dumps(generation_settings, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_chat_history(db_path: str, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row # Row — есть итератор бд по строкам
        cursor = conn.execute(
            """
            SELECT id, timestamp, username, session_id, user_message, ai_response, generation_settings
            FROM chat_history
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall() # fetchall() — есть вывод списка строк, подходящих запросу поиска
    return [dict(row) for row in rows] # как я понимаю, строка в бд — есть словарь питона. не знаю зачем здесь открытое объявление dict


def list_chat_sessions(
    db_path: str,
    username: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    base_query = """
        SELECT
            session_id,
            MIN(user_message) AS first_message,
            MAX(timestamp) AS last_timestamp,
            COUNT(*) AS messages_count
        FROM chat_history
    """ # данный запрос — есть выбор строки с session_id, наименьшим user_message (пока не знаю как это работает) и наибольшим timestamp (последнее по времени) 
    params: list[Any] = []
    if username:
        base_query += " WHERE username = ?" # с нужным username
        params.append(username)
    base_query += """
        GROUP BY session_id
        ORDER BY last_timestamp DESC
        LIMIT ?
    """ # группируем по session_id — получается несколько строк, где будут самые первые сообщения в сессии (по факту group by — есть выбор наменьшего в нашем случае в каждой группе)
    params.append(limit)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(base_query, params)
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# ---------- Model loading / inference ----------
def load_model(model_path: str, base_model: str, load_in_4bit: bool) -> None:
    """Пытается загрузить модели с помощью Unsloth, использует Transformers в случае ошибки."""
    print(f"[model] Устройство: {STATE.device}")
    if STATE.device == "cuda":
        print(f"[model] GPU: {torch.cuda.get_device_name(0)}")

    # 1) Предпочтимый вариант - Unsloth
    try:
        from unsloth import FastLanguageModel  # type: ignore

        source = model_path if os.path.isdir(model_path) else base_model
        print(f"[model] Загрузка с помощью Unsloth из: {source}")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=source,
            max_seq_length=4096,
            load_in_4bit=load_in_4bit,
            dtype=None,
        )
        FastLanguageModel.for_inference(model)
        STATE.model = model
        STATE.tokenizer = tokenizer
        print("[model] Успешно загружено.")
        return
    except Exception as e:
        print(f"[model] Загрузка с Unsloth не удалась, переход на запасной вариант: {e}")

    # 2) Запаска
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

        source = model_path if os.path.isdir(model_path) else base_model
        print(f"[model] Загрузка с помощью Transformers из: {source}")

        dtype = torch.float16 if STATE.device == "cuda" else torch.float32
        tokenizer = AutoTokenizer.from_pretrained(source, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            source,
            torch_dtype=dtype,
            trust_remote_code=True,
            device_map="auto" if STATE.device == "cuda" else None,
        )
        if STATE.device != "cuda":
            model = model.to(STATE.device)
        model.eval()

        STATE.model = model
        STATE.tokenizer = tokenizer
        print("[model] Успешно загружено.")
    except Exception as e:
        raise RuntimeError(f"Загрузка не удалась ни одним из способов: {e}") from e


def _build_chat_messages(
    message: str,
    system_prompt: Optional[str],
    images: Optional[list[str]],
    multimodal_content: bool,
) -> list[dict[str, Any]]:
    clean_message = message.strip()
    messages: list[dict[str, Any]] = []

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt.strip()}],
            }
        )

    user_content: list[dict[str, Any]] = [{"type": "text", "text": clean_message}]

    if multimodal_content:
        for image in images or []:
            image_ref = image.strip()
            if image_ref:
                user_content.append({"type": "image", "image": image_ref})
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_content})

    return messages


def generate_text(
    message: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    do_sample: bool,
    system_prompt: Optional[str],
    images: Optional[list[str]],
) -> str:
    if STATE.model is None or STATE.tokenizer is None:
        raise RuntimeError("Модель не загружена.")

    tokenizer = STATE.tokenizer
    model = STATE.model

    messages = _build_chat_messages(
        message, system_prompt, images, multimodal_content=True
    )
    try:
        inputs = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
    except(TypeError, ValueError):
        text_messages = _build_chat_messages(
            message, system_prompt, images=None, multimodal_content=False
        )
        inputs = tokenizer.apply_chat_template(
            text_messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
    inputs = {k: v.to(STATE.device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            do_sample=do_sample,
            pad_token_id=getattr(tokenizer, "eos_token_id", None),
        )

    response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()
    return response or "(нет ответа)"


# ---------- Cloudflare tunnel ----------
def _find_cloudflared_binary() -> Optional[str]:
    candidates = [
        os.getenv("CLOUDFLARED_BIN", ""),
        shutil.which("cloudflared") or "",
        shutil.which("cloudflared.exe") or "",
        os.path.join(os.getcwd(), "cloudflared"),
        os.path.join(os.getcwd(), "cloudflared.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _read_tunnel_output(proc: subprocess.Popen, out_q: queue.Queue[str]) -> None:
    if proc.stdout is None:
        return
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        out_q.put(line.rstrip()) # добавляем строки из stdout в очередь


def start_cloudflare_tunnel(port: int) -> Optional[subprocess.Popen]:
    bin_path = _find_cloudflared_binary()
    if not bin_path:
        print("[tunnel] Cloudflared не обнаружен. Установите его с помощью: winget install --id Cloudflare.cloudflared")
        return None

    cmd = [bin_path, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"]
    print(f"[tunnel] Запуск: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        print(f"[tunnel] Ошибка при запуске: {e}")
        return None

    output_q = queue.Queue()
    thread = threading.Thread(target=_read_tunnel_output, args=(proc, output_q), daemon=True)
    thread.start()

    url_regex = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")
    for _ in range(120):  # ~12 секунд поиска
        try:
            line = output_q.get(timeout=0.1)
        except queue.Empty:
            continue

        match = url_regex.search(line)
        if match:
            STATE.tunnel_url = match.group(0)
            print(f"[tunnel] URL: {STATE.tunnel_url}")
            break

    if not STATE.tunnel_url:
        print("[tunnel] URL не был обнаружен автоматически. Просмотрите логи самостоятельно.")

    return proc


def stop_tunnel_on_exit() -> None:
    proc = STATE.tunnel_process
    if proc and proc.poll() is None:
        print("[tunnel] Остановка cloudflared...")
        proc.terminate()


# ---------- API endpoints ----------
@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "AI Server",
        "version": "1.0",
        "chat_endpoint": "/chat",
        "health_endpoint": "/health",
        "model_loaded": STATE.model is not None,
        "tunnel_url": STATE.tunnel_url,
    }


@app.get("/health", tags=["meta"])
async def health_check() -> HealthResponse:
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    return HealthResponse(
        status="healthy" if STATE.model is not None else "model_not_loaded",
        model_loaded=STATE.model is not None,
        device=STATE.device,
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        tunnel_url=STATE.tunnel_url,
    )


@app.post("/chat", responses={
    503: {"description" : "Model is not loaded"},
    500: {"description" : "Generation failed with error"}
    }, tags=["chat"])
async def chat(request: ChatRequest) -> ChatResponse:
    logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s")
    logger = logging.getLogger(__name__)

    if STATE.model is None or STATE.tokenizer is None:
        logger.exception("Model is not loaded")
        raise HTTPException(status_code=503, detail="Model is not loaded.")

    try:
        result = generate_text(
            message=request.message,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            do_sample=request.do_sample,
            system_prompt=request.system_prompt,
            images=request.images,
        )
        save_chat_message( # сохраняем пару сообщение юзера - ответ ии в бд
            db_path=STATE.db_path,
            username=request.username or "Пользователь",
            session_id=request.session_id or "default",
            user_message=request.message,
            ai_response=result,
            generation_settings={
                "max_new_tokens": request.max_new_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "do_sample": request.do_sample,
                "system_prompt": request.system_prompt,
                "images_count": len(request.images or []),
            },
        )
        return ChatResponse(response=result)
    except Exception as e:
        logger.exception(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}") from e


@app.get("/chat/history/{session_id}", tags=["chat"])
async def chat_history(session_id: str, limit: int = 100) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    history = get_chat_history(STATE.db_path, session_id, safe_limit) # берем из бд истортю сообщений нужной сессии
    return {"session_id": session_id, "count": len(history), "items": history}


@app.get("/chat/sessions", tags=["chat"])
async def chat_sessions(username: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    sessions = list_chat_sessions(STATE.db_path, username=username, limit=safe_limit) # берем из бд все сессии юзера
    return {"count": len(sessions), "items": sessions}


def main() -> None:
    parser = argparse.ArgumentParser(description="AI сервер с поддержкой туннеля Cloudflare ")
    parser.add_argument("--host", default="0.0.0.0", help="Хост для сервера")
    parser.add_argument("--port", type=int, default=8000, help="Порт сервера")
    parser.add_argument("--model-path", default="./lora_model", help="Путь к модели")
    parser.add_argument(
        "--base-model",
        default="Qwen/Qwen3-VL-8B-Thinking",
        help="Запасная модель если путь основной отсутствует",
    )
    parser.add_argument("--load-in-4bit", action="store_true", default=False, help="Загрузка модели в 4-ех битной квантизации")
    parser.add_argument("--no-tunnel", action="store_true", help="Отключение запуска туннеля")
    parser.add_argument("--reload", action="store_true", help="Включение перезагрузки uvicorn")
    parser.add_argument("--db-path", default="chat_history.db", help="Путь к SQLite базе истории чатов") # если файл не существует - автоматически создает
    args = parser.parse_args()

    STATE.db_path = args.db_path
    init_chat_db(STATE.db_path)
    load_model(args.model_path, args.base_model, args.load_in_4bit)

    if not args.no_tunnel:
        STATE.tunnel_process = start_cloudflare_tunnel(args.port)

    print("\n=== Сервер готов ===")
    print(f"Local:   http://localhost:{args.port}")
    print(f"Health:  http://localhost:{args.port}/health")
    print(f"Chat:    http://localhost:{args.port}/chat")
    if STATE.tunnel_url:
        print(f"Public:  {STATE.tunnel_url}")
    else:
        print("Public:  ожидайте")
    print("====================\n")

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_tunnel_on_exit()
        sys.exit(0)

#саня
