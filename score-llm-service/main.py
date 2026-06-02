import os
import psycopg2
import psycopg2.pool
from google import genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, util
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from contextlib import contextmanager
from datetime import datetime
import traceback
import logging

# ============================================
# Configuración
# ============================================
load_dotenv()
import torch
torch.set_num_threads(1)  # Prevenir CPU thrashing con peticiones concurrentes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Cargar modelo de Embeddings local (all-MiniLM-L6-v2)
logger.info("Cargando modelo de embeddings (esto puede tomar unos segundos la primera vez)...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
logger.info("Modelo de embeddings cargado exitosamente.")

app = FastAPI(title="Score & LLM Service")

# ============================================
# Connection Pool de PostgreSQL
# ============================================
db_pool = None


def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=40,
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "yahoo_answers"),
            user=os.environ.get("DB_USER", "admin"),
            password=os.environ.get("DB_PASS", "adminpassword"),
        )
        logger.info("Connection pool de PostgreSQL inicializado (min=2, max=10).")
    return db_pool


@contextmanager
def get_db_connection():
    """Context manager que obtiene y devuelve conexiones al pool automáticamente."""
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


# ============================================
# LLM (Gemini)
# ============================================
@retry(wait=wait_exponential(multiplier=1, min=2, max=15), stop=stop_after_attempt(5))
def generate_llm_answer(question_title: str, question_content: str) -> str:
    """Genera respuesta del LLM con retry exponencial."""
    # Switch para pruebas de estrés (evitar gastar cuota)
    if os.environ.get("MOCK_LLM", "False").lower() == "true":
        return "Esta es una respuesta simulada por el sistema para aislar el rendimiento de la caché de red."

    prompt = (
        f"Por favor, responde a la siguiente pregunta de forma concisa.\n"
        f"Título: {question_title}\n"
        f"Detalles: {question_content}"
    )
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )

    if not response.text:
        raise ValueError("El LLM devolvió una respuesta vacía")

    return response.text


# ============================================
# Métricas de Calidad
# ============================================
def calculate_cosine_similarity(answer1: str, answer2: str) -> float:
    """Similitud semántica usando embeddings (all-MiniLM-L6-v2)."""
    emb1 = embedder.encode(answer1, convert_to_tensor=True)
    emb2 = embedder.encode(answer2, convert_to_tensor=True)
    cosine_score = util.cos_sim(emb1, emb2).item()
    return max(0.0, min(1.0, cosine_score))


def calculate_rouge_l(reference: str, hypothesis: str) -> float:
    """
    ROUGE-L: Mide la subsecuencia común más larga (LCS) entre dos textos.
    Captura similitud léxica/estructural, complementando la similitud semántica.
    """
    ref_tokens = reference.lower().split()
    hyp_tokens = hypothesis.lower().split()

    if not ref_tokens or not hyp_tokens:
        return 0.0

    # Calcular LCS usando programación dinámica
    m, n = len(ref_tokens), len(hyp_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_length = dp[m][n]

    # Calcular Precision, Recall, F1
    precision = lcs_length / n if n > 0 else 0.0
    recall = lcs_length / m if m > 0 else 0.0

    if precision + recall == 0:
        return 0.0

    f1 = (2 * precision * recall) / (precision + recall)
    return max(0.0, min(1.0, f1))


# ============================================
# Endpoints
# ============================================
class EvaluateRequest(BaseModel):
    question_id: int


@app.get("/health")
def health_check():
    """Health check para Docker y monitoreo."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/evaluate")
def evaluate_question(req: EvaluateRequest):
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            # Recuperar la pregunta y la mejor respuesta original
            cur.execute(
                "SELECT title, content, best_answer, llm_answer FROM questions WHERE id = %s",
                (req.question_id,)
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Pregunta no encontrada")

            title, content, best_answer, existing_llm_answer = row

            # Si ya fue procesada, devolver datos existentes
            if existing_llm_answer:
                logger.info(f"[SKIP] Pregunta {req.question_id} ya procesada anteriormente.")
                return {"message": "Ya procesada anteriormente", "question_id": req.question_id}

            # Consultar al LLM (con retry automático por exponential backoff)
            logger.info(f"[LLM] Consultando LLM para pregunta {req.question_id}...")
            llm_answer = generate_llm_answer(title, content)

            # Calcular ambas métricas de calidad
            cosine_score = calculate_cosine_similarity(best_answer, llm_answer)
            rouge_score = calculate_rouge_l(best_answer, llm_answer)

            logger.info(
                f"[SCORE] Pregunta {req.question_id}: "
                f"cosine={cosine_score:.4f}, rouge_l={rouge_score:.4f}"
            )

            # Persistir resultados en PostgreSQL
            cur.execute("""
                UPDATE questions 
                SET llm_answer = %s, score = %s, rouge_score = %s, processed_at = %s
                WHERE id = %s
            """, (llm_answer, float(cosine_score), float(rouge_score), datetime.utcnow(), req.question_id))
            conn.commit()

            return {
                "status": "success",
                "question_id": req.question_id,
                "cosine_score": round(cosine_score, 4),
                "rouge_score": round(rouge_score, 4),
                "llm_answer_preview": llm_answer[:150] + "..." if len(llm_answer) > 150 else llm_answer
            }

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Error procesando pregunta {req.question_id}: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            cur.close()
