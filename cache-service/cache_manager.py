import redis
import time
import threading
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    """
    Wrapper sobre Redis que recolecta métricas de rendimiento.
    
    Métricas recolectadas:
    - total_hits: Número de cache hits
    - total_misses: Número de cache misses
    - hit_rate: Proporción de hits sobre total de consultas
    - total_requests: Total de consultas procesadas
    - avg_hit_latency_ms: Latencia promedio de cache hits
    - avg_miss_latency_ms: Latencia promedio de cache misses
    """

    def __init__(self, host: str = "localhost", port: int = 6379):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self._lock = threading.Lock()
        self._reset_counters()
        logger.info(f"CacheManager conectado a Redis ({host}:{port})")

    def _reset_counters(self):
        self._hits = 0
        self._misses = 0
        self._hit_latencies = []
        self._miss_latencies = []
        self._start_time = time.time()

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except redis.ConnectionError:
            return False

    def get(self, key: str) -> str | None:
        """Consulta el caché y registra métricas."""
        start = time.time()
        value = self.client.get(key)
        elapsed_ms = (time.time() - start) * 1000

        with self._lock:
            if value is not None:
                self._hits += 1
                self._hit_latencies.append(elapsed_ms)
            else:
                self._misses += 1
                self._miss_latencies.append(elapsed_ms)

        return value

    def set(self, key: str, value: str, ttl: int = 3600):
        """Almacena un valor en caché con TTL."""
        self.client.setex(key, ttl, value)

    def get_metrics(self) -> dict:
        """Retorna las métricas acumuladas del caché."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            elapsed = time.time() - self._start_time

            avg_hit_latency = (
                sum(self._hit_latencies) / len(self._hit_latencies)
                if self._hit_latencies else 0.0
            )
            avg_miss_latency = (
                sum(self._miss_latencies) / len(self._miss_latencies)
                if self._miss_latencies else 0.0
            )

            # Obtener info de Redis
            try:
                info = self.client.info("memory")
                used_memory = info.get("used_memory_human", "N/A")
                maxmemory = info.get("maxmemory_human", "N/A")
            except Exception:
                used_memory = "N/A"
                maxmemory = "N/A"

            return {
                "total_requests": total,
                "total_hits": self._hits,
                "total_misses": self._misses,
                "hit_rate_percent": round(hit_rate, 2),
                "avg_hit_latency_ms": round(avg_hit_latency, 3),
                "avg_miss_latency_ms": round(avg_miss_latency, 3),
                "elapsed_seconds": round(elapsed, 2),
                "requests_per_second": round(total / elapsed, 2) if elapsed > 0 else 0,
                "redis_used_memory": used_memory,
                "redis_max_memory": maxmemory,
            }

    def reset_metrics(self):
        """Reinicia los contadores (útil entre experimentos)."""
        with self._lock:
            self._reset_counters()
        logger.info("Métricas de caché reiniciadas.")
