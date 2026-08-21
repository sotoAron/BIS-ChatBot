"""
test_chat.py — Script de prueba interactivo para validar el flujo completo:
JWT → Rate Limiter → Caché Semántica → RAG (ChromaDB) → Ollama Streaming (SSE).
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import httpx

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def generate_jwt(secret: str, user_id: int = 1, role: str = "student", name: str = "Usuario Prueba") -> str:
    header = base64.urlsafe_b64encode(json.dumps({"typ": "JWT", "alg": "HS256"}).encode()).rstrip(b"=").decode()
    payload = {
        "sub": user_id,
        "name": name,
        "role": role,
        "sesskey": "test_session_key",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f"{header}.{payload_b64}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload_b64}.{sig}"

def stream_chat(url: str, token: str, question: str, año: str = "2026", carrera: str = ""):
    endpoint = f"{url.rstrip('/')}/api/chat/stream"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "question": question,
        "año_academico": año,
        "carrera": carrera
    }

    print(f"\n💬 Pregunta: {question}")
    print(f"📡 Conectando a {endpoint} ...")
    print("🤖 Respuesta: ", end="", flush=True)

    try:
        with httpx.Client(timeout=300.0) as client:
            with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    print(f"\n❌ Error HTTP {response.status_code}: {response.read().decode('utf-8')}")
                    return

                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        data = json.loads(data_str)
                        if "chunk" in data:
                            print(data["chunk"], end="", flush=True)
                        elif data.get("done"):
                            print("\n\n✅ [Fin del stream]")
                            timings = data.get("timings")
                            if timings:
                                print("\n" + "═" * 70)
                                print("⏱️  DESGLOSE DE TIEMPOS Y PROCESO DE PENSAMIENTO:")
                                print(f"  • Rate Limit & Auth     : {timings.get('rate_limit_ms', 0):>7.2f} ms")
                                print(f"  • Intención Detectada   : {timings.get('intent_ms', 0):>7.2f} ms  [{timings.get('intent', 'N/A')}]")
                                print(f"    ➔ Destino Enrutador   : {timings.get('intent_destination', 'N/A')}")
                                print(f"  • Caché Semántica       : {timings.get('cache_ms', 0):>7.2f} ms  [{timings.get('cache_result', 'N/A')}]")
                                print(f"  • Carga Historial       : {timings.get('history_ms', 0):>7.2f} ms")
                                print(f"  • Búsqueda RAG ChromaDB : {timings.get('rag_ms', 0):>7.2f} ms  ({timings.get('rag_docs_count', 0)} chunks)")
                                print(f"  • LLM Tiempo 1er Token  : {timings.get('llm_ttft_s', 0):>7.2f} s   (Evaluación de contexto en CPU)")
                                print(f"  • LLM Generación        : {timings.get('llm_gen_s', 0):>7.2f} s   ({timings.get('llm_tokens', 0)} tokens @ {timings.get('llm_speed_tok_s', 0)} tok/s)")
                                print("  " + "─" * 66)
                                print(f"  🏁 TIEMPO TOTAL PIPELINE: {timings.get('pipeline_total_s', 0):>7.2f} s")
                                print("═" * 70)
                        elif "error" in data:
                            print(f"\n❌ [Error SSE]: {data['error']}")
    except httpx.ConnectError:
        print(f"\n❌ No se pudo conectar al backend en {url}. ¿Está el servidor corriendo?")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probar streaming del Chatbot Académico")
    parser.add_argument("--url", default="http://localhost:8000", help="URL del backend")
    parser.add_argument("--secret", default="", help="JWT_SECRET (si está vacío, intenta leer .env)")
    parser.add_argument("--query", default="¿Cuál es el horario de atención y requisitos de cursada?", help="Pregunta a realizar")
    parser.add_argument("--año", default="2026", help="Año académico para filtro RAG")
    parser.add_argument("--carrera", default="Ingeniería Informática", help="Carrera para filtro RAG")
    parser.add_argument("--user_id", type=int, default=1, help="ID de usuario Moodle")
    args = parser.parse_args()

    secret = args.secret
    if not secret:
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("JWT_SECRET="):
                        secret = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    if not secret:
        secret = "dev-only-insecure-secret-change-in-production"

    token = generate_jwt(secret, user_id=args.user_id)
    stream_chat(args.url, token, args.query, args.año, args.carrera)
