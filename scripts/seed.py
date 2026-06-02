import csv
import psycopg2
import sys
import os
import argparse


def get_db_config():
    """Lee la configuración de DB desde variables de entorno."""
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": os.environ.get("DB_PORT", "5436"),
        "dbname": os.environ.get("DB_NAME", "yahoo_answers"),
        "user": os.environ.get("DB_USER", "admin"),
        "password": os.environ.get("DB_PASS", "adminpassword"),
    }


def seed_database(csv_file: str, limit: int):
    if not os.path.exists(csv_file):
        print(f"Error: No se encontró el archivo {csv_file}.")
        sys.exit(1)

    db_config = get_db_config()
    print(f"Conectando a PostgreSQL ({db_config['host']}:{db_config['port']})...")

    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        # Limpiar tabla para idempotencia (poder re-ejecutar sin duplicar)
        print("Limpiando tabla 'questions' para inserción limpia...")
        cur.execute("TRUNCATE TABLE questions RESTART IDENTITY CASCADE")
        conn.commit()

        print(f"Iniciando ingesta desde {csv_file} (límite: {limit} registros)...")
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, doublequote=True, escapechar='\\')

            insert_query = """
                INSERT INTO questions (class_index, title, content, best_answer)
                VALUES (%s, %s, %s, %s)
            """

            batch = []
            total_inserted = 0

            for row in reader:
                if total_inserted >= limit:
                    break

                if len(row) == 4:
                    try:
                        class_index = int(row[0])
                        batch.append((class_index, row[1], row[2], row[3]))
                        total_inserted += 1
                    except ValueError:
                        continue  # Ignorar filas malformadas

                # Insertar en lotes de 1000 para optimizar rendimiento
                if len(batch) >= 1000:
                    cur.executemany(insert_query, batch)
                    conn.commit()
                    print(f"  Insertados {total_inserted} registros...")
                    batch = []

            # Insertar registros restantes
            if batch:
                cur.executemany(insert_query, batch)
                conn.commit()

        print(f"Ingesta completada: {total_inserted} registros insertados.")

        # Verificación rápida
        cur.execute("SELECT COUNT(*) FROM questions")
        count = cur.fetchone()[0]
        print(f"Verificación: {count} registros en la tabla 'questions'.")

    except psycopg2.Error as e:
        print(f"Error de base de datos: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error inesperado: {e}")
        sys.exit(1)
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()
        print("Conexión cerrada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed de la base de datos Yahoo! Answers")
    parser.add_argument(
        "--limit", type=int,
        default=int(os.environ.get("SEED_LIMIT", 10000)),
        help="Número máximo de registros a insertar (default: 10000)"
    )
    parser.add_argument(
        "--csv", type=str,
        default=os.environ.get("CSV_FILE", "/data/test.csv"),
        help="Ruta al archivo CSV fuente"
    )
    args = parser.parse_args()

    seed_database(args.csv, args.limit)
