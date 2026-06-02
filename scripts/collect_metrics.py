import urllib.request
import json
import csv
import argparse
import os

METRICS_URL = "http://localhost:8080/metrics"
RESULTS_FILE = "../results/metrics.csv"


def collect_metrics(experiment: str, dist: str, policy: str, size: str):
    print(f"  -> Consultando métricas desde {METRICS_URL}")
    try:
        req = urllib.request.Request(METRICS_URL)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())

        # Imprimir resumen
        print(f"     Hit Rate: {data['hit_rate_percent']}% | Hits: {data['total_hits']} | Misses: {data['total_misses']}")

        # Guardar en CSV
        file_exists = os.path.isfile(RESULTS_FILE)
        with open(RESULTS_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            
            # Escribir fila de datos
            writer.writerow([
                experiment,
                dist,
                policy,
                size,
                data['total_requests'],
                data['total_hits'],
                data['total_misses'],
                data['hit_rate_percent'],
                data['avg_hit_latency_ms'],
                data['avg_miss_latency_ms'],
                data['redis_used_memory'],
                data['redis_max_memory']
            ])
            
        print(f"  -> Métricas guardadas en {RESULTS_FILE}")

    except Exception as e:
        print(f"  -> ERROR recolectando métricas: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--dist", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--size", required=True)
    args = parser.parse_args()

    # Asegurar que el directorio existe
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    
    collect_metrics(args.experiment, args.dist, args.policy, args.size)
