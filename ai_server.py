"""
AI Server for hosting Qwen3-VL model locally with Cloudflare tunnel support.
This server hosts the AI model in GPU memory and provides API endpoints for chat.
"""

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

# Import Unsloth for model loading
try:
    from unsloth import FastVisionModel
    from transformers import TextIteratorStreamer
    from threading import Thread
except ImportError:
    print("Warning: Unsloth not installed. Please install it with: pip install unsloth")
    FastVisionModel = None

# Configuration
MODEL_PATH = "lora_model"  # Path to your saved LoRA model, or use base model
BASE_MODEL = "unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit"  # Base model if LoRA not found
PORT = 8000
HOST = "0.0.0.0"

# Global variables
app = FastAPI(title="AI Chat Server", version="1.0.0")
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
    """Ensure cloudflared is installed and available."""
    if shutil.which("cloudflared") is not None:
        return True
    
    print("cloudflared not found. Please install it:")
    print("  Windows: Download from https://github.com/cloudflare/cloudflared/releases")
    print("  Or run: winget install --id Cloudflare.cloudflared")
    print("  Linux/Mac: brew install cloudflared or download from releases")
    return False


def load_model():
    """Load the Qwen3-VL model into GPU memory."""
    global model, tokenizer
    
    if FastVisionModel is None:
        raise RuntimeError("Unsloth is not installed. Please install it first.")
    
    print("Loading AI model...")
    print(f"Device: {device}")
    
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    
    try:
        # Try to load saved LoRA model first
        if os.path.exists(MODEL_PATH) and os.path.isdir(MODEL_PATH):
            print(f"Loading model from {MODEL_PATH}...")
            model, tokenizer = FastVisionModel.from_pretrained(
                MODEL_PATH,
                load_in_4bit=True,
                use_gradient_checkpointing="unsloth",
            )
            print("Model loaded from saved path.")
        else:
            # Load base model
            print(f"Loading base model: {BASE_MODEL}...")
            model, tokenizer = FastVisionModel.from_pretrained(
                BASE_MODEL,
                load_in_4bit=True,
                use_gradient_checkpointing="unsloth",
            )
            print("Base model loaded.")
        
        # Set model to evaluation mode
        FastVisionModel.for_inference(model)
        
        print("Model loaded successfully!")
        return True
        
    except Exception as e:
        print(f"Error loading model: {e}")
        raise


def generate_response(
    message: str,
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    top_p: float = 0.9,
    do_sample: bool = True,
) -> str:
    """Generate a response from the AI model."""
    global model, tokenizer
    
    if model is None or tokenizer is None:
        raise RuntimeError("Model not loaded")
    
    try:
        # Format message as a conversation
        messages = [
            {"role": "user", "content": message}
        ]
        
        # Apply chat template
        inputs = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt"
        ).to(device)
        
        # Generate response
        with torch.no_grad():
            outputs = model.generate(
                inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=do_sample,
                pad_token_id=tokenizer.eos_token_id,
            )
        
        # Decode response (skip the input tokens)
        response = tokenizer.decode(
            outputs[0][inputs.shape[1]:],
            skip_special_tokens=True
        )
        
        return response.strip()
        
    except Exception as e:
        print(f"Error generating response: {e}")
        raise


@app.on_event("startup")
async def startup_event():
    """Load model on server startup."""
    try:
        load_model()
    except Exception as e:
        print(f"Failed to load model: {e}")
        print("Server will start but chat endpoints will not work.")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
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
    """Chat endpoint - main API for interacting with the AI."""
    if model is None or tokenizer is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please check server logs."
        )
    
    if not request.message or not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )
    
    try:
        response_text = generate_response(
            message=request.message,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            do_sample=request.do_sample,
        )
        
        return ChatResponse(
            response=response_text,
            status="success"
        )
        
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "AI Chat Server",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "chat": "/chat (POST)",
        },
        "model_loaded": model is not None,
    }


def start_cloudflare_tunnel(port: int):
    """Start Cloudflare tunnel in a separate process."""
    if not ensure_cloudflared():
        print("Cloudflared not available. Server will only be accessible locally.")
        return None
    
    try:
        import time
        import threading
        
        # Start cloudflared tunnel
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr into stdout
            text=True,
            bufsize=1
        )
        
        # Function to read and print tunnel URL
        def read_tunnel_url():
            time.sleep(3)  # Give cloudflared time to start
            print("\n" + "="*50)
            print("Cloudflare Tunnel Starting...")
            print("="*50)
            print("Reading tunnel URL (this may take a few seconds)...")
            
            # Read output line by line
            url_found = False
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                # Cloudflared prints the URL in various formats
                if 'https://' in line and '.trycloudflare.com' in line:
                    # Extract URL
                    import re
                    urls = re.findall(r'https://[^\s]+\.trycloudflare\.com', line)
                    if urls:
                        print(f"✓ Public URL: {urls[0]}")
                        print(f"  Share this URL to access your server from anywhere!")
                        url_found = True
                        break
                elif 'trycloudflare.com' in line:
                    print(f"Tunnel output: {line}")
            
            if not url_found:
                print("Note: Could not automatically detect tunnel URL.")
                print("Check the cloudflared output above for the URL.")
            print("="*50 + "\n")
        
        # Start reading in background
        thread = threading.Thread(target=read_tunnel_url, daemon=True)
        thread.start()
        
        return process
        
    except Exception as e:
        print(f"Error starting Cloudflare tunnel: {e}")
        print("You can manually start a tunnel with:")
        print(f"  cloudflared tunnel --url http://localhost:{port}")
        return None


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AI Chat Server")
    parser.add_argument("--port", type=int, default=PORT, help="Server port")
    parser.add_argument("--host", type=str, default=HOST, help="Server host")
    parser.add_argument("--model-path", type=str, default=MODEL_PATH, help="Path to model")
    parser.add_argument("--no-tunnel", action="store_true", help="Don't start Cloudflare tunnel")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    
    args = parser.parse_args()
    
    # Update global variables
    PORT = args.port
    HOST = args.host
    MODEL_PATH = args.model_path
    
    # Start Cloudflare tunnel if requested
    tunnel_process = None
    if not args.no_tunnel:
        tunnel_process = start_cloudflare_tunnel(PORT)
    
    print(f"\nStarting AI Server on {HOST}:{PORT}")
    print(f"Model path: {MODEL_PATH}")
    print(f"Local URL: http://localhost:{PORT}")
    print(f"Health check: http://localhost:{PORT}/health")
    print(f"Chat endpoint: http://localhost:{PORT}/chat\n")
    
    try:
        # Run the server
        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            reload=args.reload,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if tunnel_process:
            tunnel_process.terminate()
        sys.exit(0)
