import os
import psycopg2
from google import genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, util
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
import traceback

load_dotenv()
client = genai.Client()

# Cargar modelo de Embeddings local (all-MiniLM-L6-v2)
print("Cargando modelo de embeddings (esto puede tomar unos segundos la primera vez)...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')

app = FastAPI(title="Score & LLM Service")

# Exponential Backoff para la API externa


@retry(wait=wait_exponential(multiplier=1, min=2, max=15), stop=stop_after_attempt(5))
def generate_llm_answer(question_title: str, question_content: str) -> str:
    prompt = f"Por favor, responde a la siguiente pregunta de forma concisa.\nTítulo: {question_title}\nDetalles: {question_content}"

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    return response.text


def calculate_similarity_score(answer1: str, answer2: str) -> float:
    # Convertir textos a vectores (embeddings) y calcular similitud del coseno
    emb1 = embedder.encode(answer1, convert_to_tensor=True)
    emb2 = embedder.encode(answer2, convert_to_tensor=True)
    cosine_score = util.cos_sim(emb1, emb2).item()

    # Asegurar que el score esté entre 0 y 1
    return max(0.0, min(1.0, cosine_score))


def get_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"]
    )


class EvaluateRequest(BaseModel):
    question_id: int


@app.post("/evaluate")
def evaluate_question(req: EvaluateRequest):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Recuperar la pregunta y la mejor respuesta original
        cur.execute(
            "SELECT title, content, best_answer, llm_answer FROM questions WHERE id = %s", (req.question_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=404, detail="Pregunta no encontrada")

        title, content, best_answer, existing_llm_answer = row

        # Evitar procesar si ya fue respondida (opcional, dependiendo de si se quiere sobreescribir)
        if existing_llm_answer:
            return {"message": "Ya procesada anteriormente", "question_id": req.question_id}

        # Consultar a Gemini (con retry automático)
        llm_answer = generate_llm_answer(title, content)

        # Calcular Métrica de Calidad (Similitud Semántica)
        score = calculate_similarity_score(best_answer, llm_answer)

        # Persistir los resultados en PostgreSQL
        cur.execute("""
            UPDATE questions 
            SET llm_answer = %s, score = %s
            WHERE id = %s
        """, (llm_answer, float(score), req.question_id))
        conn.commit()

        return {
            "status": "success",
            "question_id": req.question_id,
            "score": round(score, 4),
            "llm_answer_preview": llm_answer[:100] + "..."
        }

    except Exception as e:
        conn.rollback()
        print("--- ERROR CAPTURADO ---")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()
