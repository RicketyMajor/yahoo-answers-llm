import csv
import psycopg2
import sys
import os

# Configuraciones de conexión (deben coincidir con tu docker-compose.yml)
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "yahoo_answers"
DB_USER = "admin"
DB_PASS = "adminpassword"

# Ruta al dataset (asumiendo que ejecutas el script desde la carpeta 'scripts')
CSV_FILE = "../dataset/test.csv"


def seed_database():
    if not os.path.exists(CSV_FILE):
        print(f"Error: No se encontró el archivo {CSV_FILE}.")
        sys.exit(1)

    print("Conectando a la base de datos PostgreSQL...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()

        print(f"Iniciando ingesta desde {CSV_FILE}...")
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            # El texto está escapado con comillas dobles según la documentación
            reader = csv.reader(f, doublequote=True, escapechar='\\')

            insert_query = """
                INSERT INTO questions (class_index, title, content, best_answer)
                VALUES (%s, %s, %s, %s)
            """

            batch = []
            total_inserted = 0

            for row in reader:
                if len(row) == 4:
                    # Parseamos los datos: Aseguramos que class_index sea entero
                    try:
                        class_index = int(row[0])
                        batch.append((class_index, row[1], row[2], row[3]))
                        total_inserted += 1
                    except ValueError:
                        continue  # Ignorar filas malformadas si las hay

                # Insertar en lotes de 1000 para optimizar el rendimiento
                if len(batch) >= 1000:
                    cur.executemany(insert_query, batch)
                    conn.commit()
                    print(f"Insertados {total_inserted} registros...")
                    batch = []

            # Insertar cualquier registro restante que no haya completado un lote
            if batch:
                cur.executemany(insert_query, batch)
                conn.commit()
                print(f"Insertados {total_inserted} registros...")

        print("¡Ingesta (Seeding) completada con éxito!")

    except psycopg2.Error as e:
        print(f"Error de base de datos: {e}")
    except Exception as e:
        print(f"Error inesperado: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()
        print("Conexión cerrada.")


if __name__ == "__main__":
    seed_database()
