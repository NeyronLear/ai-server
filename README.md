# AI Server Setup Guide

This server hosts your Qwen3-VL AI model locally and makes it accessible via API endpoints, with optional Cloudflare tunnel support for external access.

## Prerequisites

1. **Python 3.8+**
2. **CUDA-capable GPU** with sufficient VRAM (for GPU inference)
3. **Unsloth** and related dependencies installed
4. **Cloudflared** (optional, for external access)

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements_server.txt
```

### 2. Install Cloudflared (Optional - for external access)

**Windows:**
- Download from: https://github.com/cloudflare/cloudflared/releases
- Or use: `winget install --id Cloudflare.cloudflared`
- Or use: `choco install cloudflared`

**Linux/Mac:**
```bash
# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Mac
brew install cloudflared
```

## Configuration

### Model Path

Update the `MODEL_PATH` variable in `ai_server.py` to point to your trained model:

```python
MODEL_PATH = "lora_model"  # Path to your saved LoRA model
```

Or use command line argument:
```bash
python ai_server.py --model-path "path/to/your/model"
```

## Usage

### Basic Usage (Local Only)

```bash
python ai_server.py
```

Server will start on `http://localhost:8000`

### With Cloudflare Tunnel (External Access)

```bash
python ai_server.py
```

The server will automatically start a Cloudflare tunnel if `cloudflared` is installed. You'll see a public URL like:
```
https://xxxxx.trycloudflare.com
```

### Command Line Options

```bash
python ai_server.py --help

Options:
  --port PORT          Server port (default: 8000)
  --host HOST          Server host (default: 0.0.0.0)
  --model-path PATH    Path to model directory
  --no-tunnel          Don't start Cloudflare tunnel
  --reload             Enable auto-reload (development mode)
```

### Examples

```bash
# Custom port
python ai_server.py --port 9000

# No Cloudflare tunnel
python ai_server.py --no-tunnel

# Development mode with auto-reload
python ai_server.py --reload

# Custom model path
python ai_server.py --model-path "models/my_custom_model"
```

## API Endpoints

### 1. Health Check
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
  "gpu_name": "{your_gpu_here}"
}
```

### 2. Chat Endpoint
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
  "do_sample": true
}
```

Response:
```json
{
  "response": "Hello! I'm doing well, thank you for asking...",
  "status": "success"
}
```

### 3. Root Endpoint
```
GET /
```

Returns API information and status.

## Using with Chat Interface

1. Start the server:
   ```bash
   python ai_server.py
   ```

2. Open `chat_interface.html` in your browser

3. The HTML file is configured to connect to `http://localhost:8000` by default

4. If using Cloudflare tunnel, update the `SERVER_URL` in `chat_interface.html`:
   ```javascript
   const SERVER_URL = 'https://xxxxx.trycloudflare.com';
   ```

## Troubleshooting

### Model Not Loading
- Check that the model path is correct
- Ensure you have sufficient GPU memory
- Verify Unsloth is properly installed
- Check server logs for error messages

### Cloudflare Tunnel Not Working
- Ensure `cloudflared` is installed and in PATH
- Check firewall settings
- Try running `cloudflared tunnel --url http://localhost:8000` manually

### Out of Memory Errors
- Reduce `max_new_tokens` in requests
- Use a smaller model or quantized version
- Close other GPU-intensive applications

### CORS Errors
- The server includes CORS middleware allowing all origins
- If issues persist, check browser console for specific errors

## Security Notes
 
- The server allows CORS from all origins (`allow_origins=["*"]`). For production, restrict this to your specific domain
- Cloudflare tunnel URLs are temporary and change on restart
- Consider adding authentication for production use

## Next Steps

- Add authentication/API keys
- Add conversation history/context management and prompt
- Implement rate limiting

