#!/bin/bash

# ==============================================================================
# Script para automatizar los experimentos de evaluación del sistema de caché.
# Ejecuta diferentes combinaciones de distribución de tráfico y políticas de caché.
# ==============================================================================

set -e

# Configuración base
TOTAL_REQUESTS=2000
RATE=50
SEED_LIMIT=10000

# Asegurarse de que el directorio de resultados existe
mkdir -p ../results

echo "======================================================="
echo "Iniciando Experimentos - Yahoo Answers LLM"
echo "======================================================="

# Función para ejecutar un experimento
run_experiment() {
    local dist=$1
    local policy=$2
    local size=$3
    local exp_name="${dist}_${policy}_${size}"

    echo ""
    echo "-------------------------------------------------------"
    echo "Experimento: $exp_name"
    echo "Distribución: $dist | Política: $policy | Tamaño: $size"
    echo "-------------------------------------------------------"

    # Exportar variables para el docker-compose
    export DISTRIBUTION=$dist
    export CACHE_EVICTION_POLICY=$policy
    export CACHE_MAX_MEMORY=$size
    export TOTAL_REQUESTS=$TOTAL_REQUESTS
    export RATE=$RATE

    # 1. Preparar servicios y limpiar estado
    echo "[1/4] Limpiando estado y aplicando configuraciones..."
    
    # Asegurarnos de que los servicios base estén corriendo (esto ignora el error de stop anterior)
    docker compose up -d redis cache-service
    
    # Aplicar políticas y tamaños a redis en caliente (evita reiniciar el contenedor)
    docker compose exec redis redis-cli config set maxmemory $size > /dev/null
    docker compose exec redis redis-cli config set maxmemory-policy $policy > /dev/null
    
    # Vaciar todos los datos cacheados
    docker compose exec redis redis-cli flushall > /dev/null

    # Reiniciar contadores en el cache-service
    curl -X POST http://localhost:8080/metrics/reset 2>/dev/null || true

    # 2. Ejecutar generador de tráfico (se ejecuta en foreground y luego se detiene)
    echo "[2/4] Generando tráfico ($TOTAL_REQUESTS peticiones a $RATE req/s)..."
    docker compose up traffic-generator

    # 3. Recolectar métricas
    echo "[3/4] Recolectando métricas..."
    python3 collect_metrics.py --experiment "$exp_name" --dist "$dist" --policy "$policy" --size "$size"

    echo "[4/4] Experimento $exp_name finalizado."
    sleep 2
}

# Crear el archivo CSV de métricas con cabeceras (si no existe)
if [ ! -f "../results/metrics.csv" ]; then
    echo "experiment,distribution,policy,size,total_requests,hits,misses,hit_rate,avg_hit_lat,avg_miss_lat,redis_used,redis_max" > ../results/metrics.csv
fi

# ==============================================================================
# Matriz de Experimentos
# ==============================================================================

# Experimentos con distribución POISSON (Baseline)
run_experiment "poisson" "allkeys-lru" "2mb"
run_experiment "poisson" "allkeys-lfu" "2mb"
run_experiment "poisson" "allkeys-lru" "10mb"

# Experimentos con distribución ZIPF (Realista)
run_experiment "zipf" "allkeys-lru" "2mb"
run_experiment "zipf" "allkeys-lfu" "2mb"
run_experiment "zipf" "allkeys-lru" "10mb"

echo ""
echo "======================================================="
echo "¡Batería de experimentos completada!"
echo "Los resultados están en: results/metrics.csv"
echo "Ejecute 'python scripts/analyze_results.py' para generar los gráficos."
echo "======================================================="
