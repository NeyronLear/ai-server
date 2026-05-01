Этот сервер позволяет локально запустить модель Qwen 3 VL и использовать через API, с опциональной поддержкой туннеля Cloudflare и базой данных пользователей и историй их чатов.

## Зависимости

1. **Python 3.8+**
2. **CUDA-capable GPU** с достаточным количеством VRAM
3. **Unsloth** и другие необходимые библиотеки (смотреть requirements_server.txt)
4. **Cloudflared** (необязательно)

## Установка

### 1. Установка зависимостей Python

```bash
pip install -r requirements_server.txt
```

### 2. Установка Cloudflared

**Windows:**
- Установить из: https://github.com/cloudflare/cloudflared/releases
- Или: `winget install --id Cloudflare.cloudflared`
- Или: `choco install cloudflared`

**Linux/Mac:**
```bash
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Mac
brew install cloudflared
```

## Настройка

### Путь модели

Измените переменную `MODEL_PATH` в `ai_server.py`:

```python
MODEL_PATH = "lora_model"  # Path to your saved LoRA model
```

Или используйте аргумент командной строки:
```bash
python ai_server_cf.py --model-path "path/to/your/model"
```

## Использование

### Локально

```bash
python ai_server_cf.py
```

Сервер будет запущен на `http://localhost:8000`

### С туннелем Cloudflare

```bash
python ai_server_сf.py
```

Сервер автоматически запустится если `cloudflared` установлен. Вы увидите ссылку по типу:
```
https://xxxxx.trycloudflare.com
```

### Аргументы командной строки

```bash
python ai_server_cf.py --help

Options:
  --port PORT          Номер порта для запуска сервера (8000 по умолчанию)
  --host HOST          Адрес хоста для запуска сервера (0.0.0.0 по умолчанию)
  --model-path PATH    Путь к модели ии (./lora_model по умолчанию)
  --base-model NAME    Название запасной модели, если путь основной отсутствует (Qwen/Qwen3-VL-8B-Thinking по умолчанию)
  --load-in-4bit BOOL  Загрузка в 4-х битной квантизации для оптимизации (False по умолчанию)
  --no-tunnel          Без запуска туннеля cloudflare
  --reload             Включает перезагрузку uvicorn
  --db-path NAME       Изменить нзвание базы данных историй чатов
```

### Примеры

```bash
# Другой порт
python ai_server.py --port 9000

# Без туннеля
python ai_server.py --no-tunnel

# Режим разработки с автоперезагрузкой
python ai_server.py --reload

# Свой путь к модели
python ai_server.py --model-path "models/my_custom_model"
```

## Пути API

### 1. Проверка сервера
```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "model_loaded": true/false,
  "device": "cuda"/"cpu",
  "gpu_available": true/false,
  "gpu_name": "{your_gpu_here}",
  "tunnel_url": "https://xxxxx.trycloudflare.com"
}
```

### 2. Чат
```
POST /chat
Content-Type: application/json
```

Request:
```json
{
  "message": "Hello, how are you?",
  "max_new_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.9,
  "do_sample": true,
  "system_prompt": "<системный промпт>",
  "images": [],
  "username": "user_username",
  "session_id": "<ИД сессии>",
  "request_id": "<ИД запроса>"
}
```

Response:
```json
{
  "response": "Hello! I'm doing well, thank you for asking...",
  "status": "success"
}
```

### 3. Корневой путь
```
GET /
```

Возвращает статус и информацию о сервере

### 4. Остановка генерации
```
POST /chat/stop
Content-Type: application/json
```

Request:
```json
{
  "request_id": "<ИД запроса>"
}
```

Останавливает генерацию запроса по `request_id`

### 5. Стриминг ответа
```
POST /chat/stream
Content-Type: application/json
```

Request:
```json
{
  "message": "Hello, how are you?",
  "max_new_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.9,
  "do_sample": true,
  "system_prompt": "<системный промпт>",
  "images": [],
  "username": "user_username",
  "session_id": "<ИД сессии>",
  "request_id": "<ИД запроса>"
}
```

Response: возвращает StreamingResponse

### 6. История одного чата пользователя
```
GET /chat/history/{session_id}
```

Arguments:
```json
{
  "session_id": "<ИД сессии>",
  "limit": 100,
  "username": "user_username"
}

Response:
```json
{
  "session_id": "<ИД сессии>",
  "count": 100,
  "items": [{}]
}
```

### 7. Все истории чатов одного пользователя
```
GET /chat/sessions
```

Arguments:
```json
{
  "username": "user_username",
  "limit": 50
}
```

Response:
```json
{
  "count": 50,
  "items": [{}]
}
```

### 8. Установка глобального промпта (admin-only)
```
POST /admin/update-prompt
Content-Type: application/json
```

Request:
```json
{
  "new_prompt": "<промпт>",
  "user_role": "<роль пользователя-отправителя>"
}
```

### 9. Список пользователей
```
GET /users
```

Response:
```json
{
  "count": 100,
  "items": [{}]
}
```

### 10. Вход пользователей на сайт
```
POST /auth/login
Content-Type: application/json
```

Request:
```json
{
  "username" : "user_username",
  "password": "user_password",
  "mode": "user"/"admin"
}
```

Response:
```json
{
  "status": "success",
  "item": {
    "id": "id",
    "username": "user_username",
    "role": "user"/"admin",
    "created_at": "date_created_at",
    "updated_at": "date_updated_at",
  }
}
```

### 11. Проверка активных пользователей
```
POST /auth/heartbeat
Content-Type: application/json
```

Request:
```json
{
  "username": "user_username"
}
```

Response:
```json
{
  "status": "success"
}
```

### 12. Статистика активных пользователей (admin-only)
```
GET /admin/stats
```

Arguments:
```json
{
  "user_role": "admin"/"user"
}

Response:
```json
{
  "active_users": 100
}
```

### 13. Создание, изменение, удаление пользователей

#### 1. Создание
```
POST /users
Content-Type: application/json
```

Request:
```json
{
  "username": "user-username",
  "role": "admin"/"user",
  "user_role": "admin"/"user" (роль создающего),
  "user_password": "<пароль созданного пользователя>"
}
```

#### 2. Изменение
```
PUT /users/{user_id}
```

Request:
```json
{
  "username": "user_username",
  "role": "admin"/"user",
  "user_role": "admin"/"user" (роль изменяющего)
}
```

### 3. Удаление
```
DELETE /users/{user_id}
```

Arguments:
```json
{
  "user_id": "<ИД удаляемого пользователя>",
  "user_role": "admin"/"user" (роль удаляющего)
}
```

## Использование вместе с сайтом

1. Запустить сервер:
   ```bash
   python ai_server_cf.py
   ```

2. Открыть `сайт.html` в браузере

3. Войдите в базовый аккаунт админа (логин и пароль находятся в работа.js)

4. В настройках вставьте URL туннеля Cloudflare

## Решение проблем

### Модель не загружается
- Проверьте путь к модели
- Убедитесь, что у вас достаточно VRAM
- Убедитесь, что все библиотеки установлены
- Проверьте логи сервера

### Не работает туннель Cloudflare
- Убедитесь, что `cloudflared` установлен 
- Проверьте настройки брандмауэра
- Попробуйте самостоятельно запустить туннель с помощтю `cloudflared tunnel --url http://localhost:8000` 

### Ошибки OOM
- Уменьшите `max_new_tokens` 
- Используйте меньшую модель
- закройте приложения, забирающие VRAM

### Ошибки CORS
- Проверьте консоль браузера на специфические ошибки

## Пометка о безопасности
 
- Сервер разрешает все источники с помощью CORS (`allow_origins=["*"]`)
- URL туннеля меняется с каждым перезапуском

