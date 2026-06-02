import os
import json
import httpx
import psycopg2
import psycopg2.pool
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import contextmanager
from datetime import datetime
from cache_manager import CacheManager
import logging
import traceback

# ============================================
# Configuración
# ============================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cache Service (Proxy)")

SCORE_SERVICE_URL = os.environ.get("SCORE_SERVICE_URL", "http://score-llm-service:8001")
CACHE_TTL = int(os.environ.get("CACHE_TTL", 3600))

# ============================================
# Caché (Redis)
# ============================================
cache = CacheManager(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
)

# ============================================
# Connection Pool de PostgreSQL
# ============================================
db_pool = None


def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "yahoo_answers"),
            user=os.environ.get("DB_USER", "admin"),
            password=os.environ.get("DB_PASS", "adminpassword"),
        )
        logger.info("Connection pool de PostgreSQL inicializado.")
    return db_pool


@contextmanager
def get_db_connection():
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


# ============================================
# Modelos
# ============================================
class QueryRequest(BaseModel):
    question_id: int


class QueryResponse(BaseModel):
    question_id: int
    source: str  # "cache" o "llm"
    llm_answer: str | None = None
    cosine_score: float | None = None
    rouge_score: float | None = None


# ============================================
# Endpoints
# ============================================
@app.get("/health")
def health_check():
    redis_ok = cache.ping()
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/metrics")
def get_metrics():
    """
    Devuelve las métricas acumuladas de caché.
    Endpoint clave para el análisis empírico del sistema.
    """
    return cache.get_metrics()


@app.post("/metrics/reset")
def reset_metrics():
    """Reinicia los contadores de métricas (útil entre experimentos)."""
    cache.reset_metrics()
    return {"status": "metrics reset"}


@app.post("/query")
def handle_query(req: QueryRequest):
    """
    Punto de entrada principal del pipeline.
    
    Flujo (según Figura 1 del proyecto):
    1. Verificar si la respuesta está en caché (Redis).
    2. Si HIT: devolver dato cacheado + incrementar access_count en DB.
    3. Si MISS: delegar al score-llm-service → cachear resultado → devolver.
    """
    cache_key = f"question:{req.question_id}"

    # --- 1. Consultar Caché ---
    cached_data = cache.get(cache_key)

    if cached_data is not None:
        # === CACHE HIT ===
        logger.info(f"[HIT] Pregunta {req.question_id} encontrada en caché.")

        # Incrementar access_count en DB
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE questions SET access_count = access_count + 1 WHERE id = %s",
                    (req.question_id,)
                )
                conn.commit()
                cur.close()
        except Exception as e:
            logger.warning(f"Error actualizando access_count: {e}")

        data = json.loads(cached_data)
        return QueryResponse(
            question_id=req.question_id,
            source="cache",
            llm_answer=data.get("llm_answer"),
            cosine_score=data.get("cosine_score"),
            rouge_score=data.get("rouge_score"),
        )

    # === CACHE MISS ===
    logger.info(f"[MISS] Pregunta {req.question_id} no está en caché. Delegando a score-llm-service...")

    # --- 2. Delegar al Score/LLM Service ---
    try:
        with httpx.Client(timeout=60.0) as http_client:
            response = http_client.post(
                f"{SCORE_SERVICE_URL}/evaluate",
                json={"question_id": req.question_id}
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Score service respondió con error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=502, detail=f"Score service error: {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"No se pudo conectar con score-llm-service: {e}")
        raise HTTPException(status_code=503, detail="Score service no disponible")

    # --- 3. Cachear resultado completo ---
    cache_value = json.dumps({
        "llm_answer": result.get("llm_answer_preview", ""),
        "cosine_score": result.get("cosine_score"),
        "rouge_score": result.get("rouge_score"),
    })
    cache.set(cache_key, cache_value, ttl=CACHE_TTL)

    # Incrementar access_count en DB (primera vez)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE questions SET access_count = access_count + 1 WHERE id = %s",
                (req.question_id,)
            )
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning(f"Error actualizando access_count: {e}")

    return QueryResponse(
        question_id=req.question_id,
        source="llm",
        llm_answer=result.get("llm_answer_preview"),
        cosine_score=result.get("cosine_score"),
        rouge_score=result.get("rouge_score"),
    )
