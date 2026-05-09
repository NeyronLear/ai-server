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
    --db-path <str> - изменить нзвание бд историй чатов
"""

import argparse
import asyncio
import concurrent.futures
import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional
import logging
import time

import bcrypt

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    request_id: Optional[str] = Field(default=None, description="ID запроса генерации")


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


class AdminPromptRequest(BaseModel):
    new_prompt: str = ""
    user_role: str = "user"


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: str = Field(default="user")
    user_role: str = Field(default="user", description="Роль того, кто выполняет действие")
    user_password: str = Field(default="", description="Пароль созданного пользователя")


class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[str] = None
    user_role: str = Field(default="user", description="Роль того, кто выполняет действие")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(default="")
    mode: str = Field(default="user", description="Режим входа: user/admin")


class HeartbeatRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)


# ---------- Global runtime state ----------
@dataclass # автоматически создают __init__ для класса, в котором инициализирует данные. по сути генератор шаблона на лету
class RuntimeState:
    model: Optional[object] = None
    tokenizer: Optional[object] = None
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    tunnel_url: Optional[str] = None
    db_path: str = "chat_history.db"


STATE = RuntimeState()
admin_prompt = ""
ACTIVE_USERS: dict[str, float] = {}
ACTIVE_USERS_TTL_SECONDS = 120

# инференс не блокирует event loop
# подача запросов на видеокарту идет по порядку
INFERENCE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="ai_infer",
)


# ---------- FastAPI app ----------
app = FastAPI(title="AI Server", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # разрешены ВСЕ источники
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Chat history database ----------
def init_chat_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn: # conn — есть соединение с нашей бд
        conn.execute( # execute — есть передача команды в sql
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


def init_users_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
                password_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def list_users(db_path: str, include_password_hash: bool = False) -> list[dict[str, Any]]:
    select_fields = "id, username, role, created_at, updated_at"
    if include_password_hash:
        select_fields = "id, username, role, password_hash, created_at, updated_at"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            f"""
            SELECT {select_fields}
            FROM users
            ORDER BY id DESC
            """
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def create_user(db_path: str, username: str, role: str, password: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, role, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username.strip(), role, password_hash, now, now),
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, username, role, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else {}


def update_user(db_path: str, user_id: int, username: Optional[str], role: Optional[str]) -> Optional[dict[str, Any]]:
    fields: list[str] = []
    params: list[Any] = []
    if username is not None:
        fields.append("username = ?")
        params.append(username.strip())
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if not fields:
        return get_user_by_id(db_path, user_id)

    fields.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z")
    params.append(user_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
    return get_user_by_id(db_path, user_id)


def get_user_by_id(db_path: str, user_id: int) -> Optional[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, username, role, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_user(db_path: str, user_id: int) -> bool:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return cursor.rowcount > 0


def get_user_credentials(db_path: str, username: str) -> Optional[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, username, role, password_hash, created_at, updated_at
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (username.strip(),),
        ).fetchone()
    return dict(row) if row else None


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    normalized_hash = password_hash
    if normalized_hash.startswith("b'") and normalized_hash.endswith("'"):
        normalized_hash = normalized_hash[2:-1]
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            normalized_hash.encode("utf-8"),
        )
    except ValueError:
        return False


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
                datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
                username or "Пользователь",
                session_id or "default",
                user_message,
                ai_response,
                json.dumps(generation_settings, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_chat_history(
    db_path: str,
    session_id: str,
    limit: int = 100,
    username: Optional[str] = None,
) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row # Row — есть итератор бд по строкам
        if username:
            cursor = conn.execute(
                """
                SELECT id, timestamp, username, session_id, user_message, ai_response, generation_settings
                FROM chat_history
                WHERE session_id = ? AND username = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, username, limit),
            )
        else:
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

    # 1) предпочтимый вариант - Unsloth
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

    # 2) запаска
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

    user_content = [{"type": "text", "text": clean_message}]

    if multimodal_content:
        for image in images or []:
            image_ref = image.strip()
            if image_ref:
                user_content.append({"type": "image", "image": image_ref})
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_content})

    return messages


def _compose_context_messages(
    db_path: str,
    username: str,
    session_id: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows = get_chat_history(
        db_path=db_path,
        session_id=session_id,
        limit=max(1, min(limit, 50)),
        username=username,
    )
    if not rows:
        return []
    rows.reverse()
    context_messages: list[dict[str, Any]] = []
    for row in rows:
        user_text = (row.get("user_message") or "").strip()
        ai_text = (row.get("ai_response") or "").strip()
        if user_text:
            context_messages.append(
                {"role": "user", "content": [{"type": "text", "text": user_text}]}
            )
        if ai_text:
            context_messages.append(
                {"role": "assistant", "content": [{"type": "text", "text": ai_text}]}
            )
    return context_messages


def _build_effective_prompt(user_system_prompt: Optional[str]) -> Optional[str]:
    if admin_prompt and user_system_prompt:
        return f"{admin_prompt}\n{user_system_prompt}"
    if admin_prompt:
        return admin_prompt
    return user_system_prompt


def _prepare_model_inputs(
    message: str,
    system_prompt: Optional[str],
    images: Optional[list[str]],
    context_messages: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    if STATE.tokenizer is None:
        raise RuntimeError("Токенизатор не загружен.")
    tokenizer = STATE.tokenizer
    messages = _build_chat_messages(
        message, system_prompt, images, multimodal_content=True
    )
    if context_messages:
        if messages and messages[0].get("role") == "system":
            system_msg = messages[0]
            user_tail = messages[1:]
            messages = [system_msg, *context_messages, *user_tail]
        else:
            messages = [*context_messages, *messages]
    try:
        inputs = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
    except (TypeError, ValueError):
        text_messages = _build_chat_messages(
            message, system_prompt, images=None, multimodal_content=False
        )
        if context_messages:
            if text_messages and text_messages[0].get("role") == "system":
                text_messages = [text_messages[0], *context_messages, *text_messages[1:]]
            else:
                text_messages = [*context_messages, *text_messages]
        inputs = tokenizer.apply_chat_template(
            text_messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
    return {k: v.to(STATE.device) for k, v in inputs.items()}


def generate_text(
    message: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    do_sample: bool,
    system_prompt: Optional[str],
    images: Optional[list[str]],
    context_messages: Optional[list[dict[str, Any]]] = None,
) -> str:
    if STATE.model is None or STATE.tokenizer is None:
        raise RuntimeError("Модель не загружена.")

    tokenizer = STATE.tokenizer
    model = STATE.model

    inputs = _prepare_model_inputs(
        message=message,
        system_prompt=system_prompt,
        images=images,
        context_messages=context_messages,
    )

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
    response = "<think>\n" + response
    return response or "(нет ответа)"


def _chat_inference(request: ChatRequest) -> str:
    """Синхронная часть /chat: контекст, генерация, запись в БД. Выполняется в пуле потоков."""
    if STATE.model is None or STATE.tokenizer is None:
        raise RuntimeError("Model is not loaded.")

    effective_system_prompt = _build_effective_prompt(request.system_prompt)
    context_messages = _compose_context_messages(
        db_path=STATE.db_path,
        username=request.username or "Пользователь",
        session_id=request.session_id or "default",
        limit=12,
    )
    result = generate_text(
        message=request.message,
        max_new_tokens=request.max_new_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        do_sample=request.do_sample,
        system_prompt=effective_system_prompt,
        images=request.images,
        context_messages=context_messages,
    )
    save_chat_message(
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
    return result


# ---------- CloudPub tunnel ----------
def start_cloudpub_tunnel(port: int) -> Optional[str]:
    from cloudpub_python_sdk import Connection, Protocol, Auth

    global conn, endpoint

    email = os.getenv("CLOUDPUB_EMAIL")
    password = os.getenv("CLOUDPUB_PASS")

    if not email or not password:
        try:
            from google.colab import userdata

            email = email or userdata.get("email")
            password = password or userdata.get("pass")
        except Exception as e:
            print(f"[Tunnel] Не удалось прочитать Colab userdata: {e}")

    if not email or not password:
        print("[Tunnel] CLOUDPUB_EMAIL/CLOUDPUB_PASS не заданы. Туннель отключен.")
        return None

    conn = Connection(email=email, password=password)

    endpoint = conn.publish(
        Protocol.HTTP,
        f"http://localhost:{port}",
        name="ai-server",
        auth=Auth.NONE
    )

    return endpoint.url


# ---------- API endpoints ----------
@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "AI Server",
        "version": "1.5",
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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            INFERENCE_EXECUTOR,
            _chat_inference,
            request,
        )
        return ChatResponse(response=result)
    except RuntimeError as e:
        if "not loaded" in str(e).lower():
            raise HTTPException(status_code=503, detail="Model is not loaded.") from e
        logger.exception(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}") from e
    except Exception as e:
        logger.exception(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}") from e


@app.get("/chat/history/{session_id}", tags=["chat"])
async def chat_history(
    session_id: str,
    limit: int = 100,
    username: Optional[str] = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    history = get_chat_history(
        STATE.db_path,
        session_id,
        safe_limit,
        username=username,
    ) # берем из бд историю сообщений нужной сессии
    return {"session_id": session_id, "count": len(history), "items": history}


@app.get("/chat/sessions", tags=["chat"])
async def chat_sessions(username: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    sessions = list_chat_sessions(STATE.db_path, username=username, limit=safe_limit) # берем из бд все сессии юзера
    return {"count": len(sessions), "items": sessions}

@app.post("/admin/update-prompt", tags=["admin"], responses={403: {"description": "Forbidden action for non-admin account"}})
async def update_prompt(payload: AdminPromptRequest) -> dict[str, str]:
    if payload.user_role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden action for non-admin account")

    global admin_prompt
    admin_prompt = payload.new_prompt.strip()

    return {"status": "success", "prompt": admin_prompt}


@app.get("/users", tags=["users"])
async def get_users() -> dict[str, Any]:
    users = list_users(STATE.db_path, include_password_hash=False)
    return {"count": len(users), "items": users}


@app.post(
    "/auth/login",
    tags=["users"],
    responses={400: {"description": "Invalid data"}, 401: {"description": "Invalid credentials"}},
)
async def auth_login(payload: LoginRequest) -> dict[str, Any]:
    mode = payload.mode.strip().lower()
    if mode not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Mode must be 'user' or 'admin'")

    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username must not be empty")
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password must not be empty")

    user = get_user_credentials(STATE.db_path, username)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if mode == "admin" and user.get("role") != "admin":
        raise HTTPException(status_code=401, detail="У пользователя нет прав администратора")

    if not verify_password(payload.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    ACTIVE_USERS[user["username"]] = time.time()

    return {
        "status": "success",
        "item": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
        },
    }


@app.post("/auth/heartbeat", tags=["users"])
async def auth_heartbeat(payload: HeartbeatRequest) -> dict[str, Any]:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username must not be empty")
    ACTIVE_USERS[username] = time.time()
    return {"status": "success"}


@app.get("/admin/stats", tags=["admin"])
async def get_admin_stats(user_role: str = "user") -> dict[str, Any]:
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden action for non-admin account")
    now = time.time()
    stale_users = [
        username
        for username, last_seen in ACTIVE_USERS.items()
        if now - last_seen > ACTIVE_USERS_TTL_SECONDS
    ]
    for username in stale_users:
        ACTIVE_USERS.pop(username, None)
    return {"active_users": len(ACTIVE_USERS)}


@app.post("/users", tags=["users"], responses={400: {"description": "Invalid data"}, 403: {"description": "Forbidden action for non-admin account"}, 409: {"description": "Username already exists"}})
async def create_user_endpoint(payload: UserCreateRequest) -> dict[str, Any]:
    if payload.user_role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden action for non-admin account")
    clean_role = (payload.role or "user").strip().lower()
    if clean_role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")
    clean_username = payload.username.strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="Username must not be empty")
    clean_password = payload.user_password.strip()
    if not clean_password:
        raise HTTPException(status_code=400, detail="Password must not be empty")
    try:
        user = create_user(STATE.db_path, clean_username, clean_role, clean_password)
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e
    return {"status": "success", "item": user}


@app.put("/users/{user_id}", tags=["users"], responses={400: {"description": "Invalid data"}, 403: {"description": "Forbidden action for non-admin account"}, 404: {"description": "User not found"}, 409: {"description": "Username already exists"}})
async def update_user_endpoint(user_id: int, payload: UserUpdateRequest) -> dict[str, Any]:
    if payload.user_role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden action for non-admin account")
    clean_role = payload.role.strip().lower() if payload.role is not None else None
    if clean_role is not None and clean_role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")
    clean_username = payload.username.strip() if payload.username is not None else None
    if clean_username is not None and not clean_username:
        raise HTTPException(status_code=400, detail="Username must not be empty")
    try:
        updated = update_user(STATE.db_path, user_id, clean_username, clean_role)
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=409, detail="Username already exists") from e
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "success", "item": updated}


@app.delete("/users/{user_id}", tags=["users"], responses={403: {"description": "Forbidden action for non-admin account"}, 404: {"description": "User not found"}})
async def delete_user_endpoint(user_id: int, user_role: str = "user") -> dict[str, str]:
    if user_role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden action for non-admin account")
    deleted = delete_user(STATE.db_path, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "success"}

def main() -> None:
    global args

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
    init_users_db(STATE.db_path)
    load_model(args.model_path, args.base_model, args.load_in_4bit)

    if not args.no_tunnel:
        STATE.tunnel_url = start_cloudpub_tunnel(args.port)

    print("\n=== Сервер готов ===")
    print(f"Local:   http://localhost:{args.port}")
    print(f"Health:  http://localhost:{args.port}/health")
    print(f"Chat:    http://localhost:{args.port}/chat")
    if STATE.tunnel_url:
        print(f"Public:  {STATE.tunnel_url}")
    else:
        print("Public:  ожидайте")
    print("====================\n")

    run_uvicorn_server(args.host, args.port, args.reload)


def run_uvicorn_server(host: str, port: int, reload_enabled: bool) -> None:
    """Запускает uvicorn, учитывая среды с уже активным event loop (например, Colab/Jupyter)."""
    try:
        asyncio.get_running_loop()
        running_loop = True
    except RuntimeError:
        running_loop = False

    if not running_loop:
        uvicorn.run(app, host=host, port=port, reload=reload_enabled, log_level="info")
        return

    effective_reload = reload_enabled
    if reload_enabled:
        print("[warn] Обнаружен активный event loop; запускаю без --reload.")
        effective_reload = False

    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host=host, port=port, reload=effective_reload, log_level="info"),
        name="uvicorn-server-thread",
        daemon=False,
    )
    server_thread.start()
    server_thread.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if not args.no_tunnel and conn is not None and endpoint is not None:
            conn.unpublish(endpoint.guid)
        sys.exit(0)