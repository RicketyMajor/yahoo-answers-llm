import os
import psycopg2
import matplotlib.pyplot as plt
import numpy as np
import csv

# Configuración DB
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5436")
DB_NAME = os.environ.get("DB_NAME", "yahoo_answers")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASS = os.environ.get("DB_PASS", "adminpassword")

RESULTS_DIR = "../results"

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )

def ensure_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)

# ==============================================================================
# ANÁLISIS DE CACHÉ
# ==============================================================================
def plot_cache_metrics():
    metrics_file = f"{RESULTS_DIR}/metrics.csv"
    if not os.path.exists(metrics_file):
        print(f"No se encontró {metrics_file}. Ejecute run_experiments.sh primero.")
        return

    print("Generando gráficos de caché...")
    
    experiments = []
    with open(metrics_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            experiments.append(row)

    if not experiments:
        print("El archivo metrics.csv está vacío.")
        return

    # 1. Comparativa de Hit Rate: Poisson vs Zipf
    plt.figure(figsize=(10, 6))
    
    poisson_exp = [e for e in experiments if e['distribution'] == 'poisson']
    zipf_exp = [e for e in experiments if e['distribution'] == 'zipf']
    
    labels = [f"{e['policy']}\n{e['size']}" for e in poisson_exp]
    
    x = np.arange(len(labels))
    width = 0.35

    poisson_hits = [float(e['hit_rate']) for e in poisson_exp]
    zipf_hits = [float(e['hit_rate']) for e in zipf_exp]

    fig, ax = plt.subplots(figsize=(10, 6))
    rects1 = ax.bar(x - width/2, poisson_hits, width, label='Poisson')
    rects2 = ax.bar(x + width/2, zipf_hits, width, label='Zipf')

    ax.set_ylabel('Hit Rate (%)')
    ax.set_title('Hit Rate por Distribución y Configuración')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.set_ylim([0, 100])

    # Añadir valores sobre las barras
    for rects in [rects1, rects2]:
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.1f}%',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom')

    plt.tight_layout()
    plt.savefig(f"{RESULTS_DIR}/hit_rate_comparison.png")
    plt.close()
    print(f" -> Guardado: {RESULTS_DIR}/hit_rate_comparison.png")

# ==============================================================================
# ANÁLISIS DE SCORE / CALIDAD
# ==============================================================================
def plot_score_metrics():
    print("Conectando a base de datos para extraer métricas de score...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Extraer registros procesados
        cur.execute("SELECT score, rouge_score FROM questions WHERE score IS NOT NULL")
        rows = cur.fetchall()
        
        if not rows:
            print("No hay suficientes datos procesados en la base de datos.")
            return

        cosine_scores = [float(r[0]) for r in rows if r[0] is not None]
        rouge_scores = [float(r[1]) for r in rows if r[1] is not None]

        # 2. Histograma de Cosine Similarity
        plt.figure(figsize=(8, 5))
        plt.hist(cosine_scores, bins=20, color='skyblue', edgecolor='black')
        plt.title('Distribución de Similitud Semántica (Cosine)')
        plt.xlabel('Score')
        plt.ylabel('Frecuencia')
        plt.grid(axis='y', alpha=0.75)
        plt.savefig(f"{RESULTS_DIR}/hist_cosine.png")
        plt.close()
        print(f" -> Guardado: {RESULTS_DIR}/hist_cosine.png")

        # 3. Histograma de ROUGE-L
        plt.figure(figsize=(8, 5))
        plt.hist(rouge_scores, bins=20, color='lightgreen', edgecolor='black')
        plt.title('Distribución de Similitud Léxica (ROUGE-L)')
        plt.xlabel('Score')
        plt.ylabel('Frecuencia')
        plt.grid(axis='y', alpha=0.75)
        plt.savefig(f"{RESULTS_DIR}/hist_rouge.png")
        plt.close()
        print(f" -> Guardado: {RESULTS_DIR}/hist_rouge.png")

        # 4. Scatter Plot: Cosine vs ROUGE-L
        plt.figure(figsize=(8, 8))
        plt.scatter(cosine_scores, rouge_scores, alpha=0.5, color='purple')
        plt.title('Similitud Semántica vs Léxica')
        plt.xlabel('Cosine Similarity')
        plt.ylabel('ROUGE-L Score')
        plt.grid(True, linestyle='--', alpha=0.7)
        
        # Añadir línea de tendencia
        if len(cosine_scores) > 1:
            z = np.polyfit(cosine_scores, rouge_scores, 1)
            p = np.poly1d(z)
            plt.plot(cosine_scores, p(cosine_scores), "r--", alpha=0.8)

        plt.savefig(f"{RESULTS_DIR}/scatter_scores.png")
        plt.close()
        print(f" -> Guardado: {RESULTS_DIR}/scatter_scores.png")

        # 5. Access Count (Zipf Validation)
        cur.execute("SELECT id, access_count FROM questions WHERE access_count > 0 ORDER BY access_count DESC LIMIT 50")
        access_rows = cur.fetchall()
        
        if access_rows:
            ids = [str(r[0]) for r in access_rows]
            counts = [r[1] for r in access_rows]
            
            plt.figure(figsize=(12, 5))
            plt.bar(ids[:30], counts[:30], color='orange')
            plt.title('Top 30 Preguntas Más Consultadas (Verificación Zipf)')
            plt.xlabel('ID de Pregunta')
            plt.ylabel('Cantidad de Accesos')
            plt.xticks(rotation=90)
            plt.tight_layout()
            plt.savefig(f"{RESULTS_DIR}/top_accesses.png")
            plt.close()
            print(f" -> Guardado: {RESULTS_DIR}/top_accesses.png")

    except Exception as e:
        print(f"Error analizando base de datos: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    ensure_dir()
    plot_cache_metrics()
    plot_score_metrics()
    print("¡Análisis completado!")
