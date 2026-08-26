"""
scripts/evaluate_golden_dataset.py

Suite de Evaluación Automatizada (Golden Dataset) para medir la precisión y
robustez de la arquitectura Híbrida + Enrutador de Intenciones + Fallback.

Alineado con los principios de la skill chatbot-flow-design:
- Intent Recognition Rate
- RAG Grounding Verification (Chunks recuperados)
- Latency & Fallback Analysis
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Optional
import httpx

# Golden Dataset de Preguntas y su Intención/Respuesta Esperada.
GOLDEN_DATASET = [
    # --- RAG: Consultas Académicas ---
    {"query": "¿Quiénes son los profesores de la materia?", "expected_intent": "RAG", "tags": "docentes, chunk_0"},
    {"query": "¿Qué días curso y en qué aula?", "expected_intent": "RAG", "tags": "dias, aula"},
    {"query": "¿Cuáles son las condiciones para promocionar?", "expected_intent": "RAG", "tags": "condiciones"},
    {"query": "¿Cuál es la carga horaria total de AACSW?", "expected_intent": "RAG", "tags": "bm25_sigla, tabla"},
    {"query": "quiero saber la fecha del primer parcial", "expected_intent": "RAG", "tags": "fechas"},
    
    # --- Moodle Tools (Intent Router Restringido) ---
    {"query": "cuál es mi nota", "expected_intent": "GRADES", "tags": "moodle, notas"},
    {"query": "qué nota me saqué en el parcial", "expected_intent": "GRADES", "tags": "moodle, notas"},
    {"query": "mis tareas pendientes", "expected_intent": "ASSIGNMENTS", "tags": "moodle, tareas"},
    {"query": "qué cursos estoy inscripto", "expected_intent": "COURSES", "tags": "moodle, cursos"},
    {"query": "agendar examen el lunes", "expected_intent": "CALENDAR_WRITE", "tags": "moodle, calendario"},
    {"query": "quiero sincronizar el pdf nuevo", "expected_intent": "SYNC", "tags": "moodle, admin"},

    # --- Ambigüedades / Fallback / Reglas Académicas ---
    {"query": "¿Cuándo juega la selección?", "expected_intent": "RAG", "tags": "out_of_domain, fallback"},
    {"query": "¿Cómo me doy de baja en la facultad?", "expected_intent": "RAG", "tags": "admin, fallback"},
    {"query": "¿Qué nota se necesita para aprobar?", "expected_intent": "RAG", "tags": "academico, no_moodle"},
]

def load_secret(cli_secret: str = "") -> str:
    """Obtiene el JWT_SECRET desde CLI, archivo .env o fallback."""
    if cli_secret:
        return cli_secret
    # Buscar .env en el directorio actual o en la raíz del backend
    env_paths = [".env", os.path.join(os.path.dirname(__file__), "..", ".env")]
    for path in env_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("JWT_SECRET="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass
    return "dev-only-insecure-secret-change-in-production"

def generate_jwt(secret: str, user_id: int = 1, role: str = "student", name: str = "Tester") -> str:
    header = base64.urlsafe_b64encode(json.dumps({"typ": "JWT", "alg": "HS256"}).encode()).rstrip(b"=").decode()
    payload = {
        "sub": user_id,
        "name": name,
        "role": role,
        "sesskey": "test_session",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f"{header}.{payload_b64}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload_b64}.{sig}"

async def evaluate_query(
    client: httpx.AsyncClient,
    api_url: str,
    token: str,
    case: dict,
    verbose: bool = False,
) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "question": case["query"],
        "año_academico": "2026",
        "carrera": "Ingeniería Informática",
    }
    
    t0 = time.perf_counter()
    response_text = ""
    timings = {}
    error_msg = None
    status_code = None
    
    try:
        async with client.stream("POST", api_url, headers=headers, json=payload, timeout=120.0) as response:
            status_code = response.status_code
            if response.status_code != 200:
                body = await response.aread()
                error_msg = f"HTTP {response.status_code}: {body.decode('utf-8', errors='replace')}"
                return {
                    "case": case,
                    "success": False,
                    "error": error_msg,
                    "status_code": status_code,
                    "duration_s": time.perf_counter() - t0,
                }
                
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                        if "chunk" in data:
                            response_text += data["chunk"]
                        elif data.get("done"):
                            timings = data.get("timings", {})
                        elif "error" in data:
                            error_msg = data["error"]
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        error_msg = str(exc)
        
    duration = time.perf_counter() - t0
    intent_detected = timings.get("intent", "UNKNOWN")
    rag_chunks = timings.get("rag_chunks", [])
    cache_result = timings.get("cache_result", "N/A")
    intent_ok = (intent_detected == case["expected_intent"])
    
    return {
        "case": case,
        "success": (error_msg is None and intent_ok),
        "intent_ok": intent_ok,
        "intent_detected": intent_detected,
        "expected_intent": case["expected_intent"],
        "rag_chunks": rag_chunks,
        "cache_result": cache_result,
        "response_text": response_text.strip(),
        "timings": timings,
        "error": error_msg,
        "status_code": status_code,
        "duration_s": duration,
    }

async def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Evaluación Automatizada Golden Dataset (Flow Design)")
    parser.add_argument("--url", default="http://localhost:8000/api/chat/stream", help="URL del endpoint de streaming")
    parser.add_argument("--secret", default="", help="JWT_SECRET (si está vacío, se lee desde .env)")
    parser.add_argument("--limit", type=int, default=0, help="Limitar número de casos a evaluar (0 = todos)")
    parser.add_argument("--index", type=int, default=0, help="Evaluar solo un caso por índice (1-indexed)")
    parser.add_argument("--verbose", action="store_true", help="Mostrar respuesta completa de cada caso")
    args = parser.parse_args()

    secret = load_secret(args.secret)
    token = generate_jwt(secret)

    cases = GOLDEN_DATASET
    if args.index > 0 and args.index <= len(GOLDEN_DATASET):
        cases = [GOLDEN_DATASET[args.index - 1]]
    elif args.limit > 0:
        cases = GOLDEN_DATASET[:args.limit]

    print("═" * 70)
    print(" 🚀 INICIANDO EVALUACIÓN DE GOLDEN DATASET (Chatbot Flow Design)")
    print(f" • Total Casos a evaluar : {len(cases)}")
    print(f" • Endpoint              : {args.url}")
    print(f" • JWT Secret Fuente     : {'CLI' if args.secret else 'Archivo .env / Default'}")
    print("═" * 70 + "\n")

    results = []
    intents_correct = 0

    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] ▶ '{case['query']}'")
            print(f"      Etiquetas: [{case['tags']}] | Esperado: {case['expected_intent']}")
            
            res = await evaluate_query(client, args.url, token, case, verbose=args.verbose)
            results.append(res)
            
            if res.get("error"):
                print(f"      ❌ Error: {res['error']}")
            else:
                intent_mark = "✅" if res["intent_ok"] else "⚠️"
                if res["intent_ok"]:
                    intents_correct += 1
                chunks_info = f" | Chunks: {res['rag_chunks']}" if res['rag_chunks'] else ""
                print(f"      {intent_mark} Intención: {res['intent_detected']} | Caché: {res['cache_result']}{chunks_info} | Tiempo: {res['duration_s']:.2f}s")
                
                resp_preview = res['response_text'].replace('\n', ' ')
                if args.verbose:
                    print(f"      🤖 Respuesta Completa:\n{res['response_text']}\n")
                else:
                    preview = resp_preview[:120] + ("..." if len(resp_preview) > 120 else "")
                    print(f"      🤖 Respuesta: \"{preview}\"")
            print("-" * 70)

    # ── Resumen de Métricas (chatbot-flow-design) ──────────────────────────
    total = len(cases)
    acc = (intents_correct / total * 100) if total > 0 else 0
    avg_time = sum(r["duration_s"] for r in results) / total if total > 0 else 0

    print("\n" + "═" * 70)
    print(" 📊 RESUMEN DE MÉTRICAS (chatbot-flow-design):")
    print(f"  • Intent Recognition Accuracy : {intents_correct}/{total} ({acc:.1f}%)")
    print(f"  • Tiempo promedio por consulta: {avg_time:.2f}s")
    print("═" * 70)

if __name__ == "__main__":
    asyncio.run(main())
