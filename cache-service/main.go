package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type Metrics struct {
	sync.Mutex
	Hits          int
	Misses        int
	HitLatencies  []float64
	MissLatencies []float64
	StartTime     time.Time
}

var (
	redisClient *redis.Client
	dbPool      *pgxpool.Pool
	metrics     = Metrics{StartTime: time.Now()}
	scoreURL    string
	cacheTTL    time.Duration
)

func initEnv() {
	scoreURL = getEnv("SCORE_SERVICE_URL", "http://score-llm-service:8001")
	ttlStr := getEnv("CACHE_TTL", "3600")
	ttl, _ := strconv.Atoi(ttlStr)
	cacheTTL = time.Duration(ttl) * time.Second
}

func getEnv(key, defaultVal string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return defaultVal
}

func initDB(ctx context.Context) error {
	connStr := fmt.Sprintf("postgres://%s:%s@%s:%s/%s",
		getEnv("DB_USER", "admin"),
		getEnv("DB_PASS", "adminpassword"),
		getEnv("DB_HOST", "db"),
		getEnv("DB_PORT", "5432"),
		getEnv("DB_NAME", "yahoo_answers"))

	poolConfig, err := pgxpool.ParseConfig(connStr)
	if err != nil {
		return err
	}
	poolConfig.MaxConns = 40

	dbPool, err = pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return err
	}
	return dbPool.Ping(ctx)
}

func initRedis(ctx context.Context) error {
	addr := fmt.Sprintf("%s:%s", getEnv("REDIS_HOST", "redis"), getEnv("REDIS_PORT", "6379"))
	redisClient = redis.NewClient(&redis.Options{
		Addr: addr,
	})
	return redisClient.Ping(ctx).Err()
}

type QueryRequest struct {
	QuestionID int `json:"question_id"`
}

type QueryResponse struct {
	QuestionID  int      `json:"question_id"`
	Source      string   `json:"source"`
	LLMAnswer   *string  `json:"llm_answer"`
	CosineScore *float64 `json:"cosine_score"`
	RougeScore  *float64 `json:"rouge_score"`
}

type ScoreResponse struct {
	Status           string  `json:"status"`
	QuestionID       int     `json:"question_id"`
	CosineScore      float64 `json:"cosine_score"`
	RougeScore       float64 `json:"rouge_score"`
	LLMAnswerPreview string  `json:"llm_answer_preview"`
}

func parseRedisMemory(info string) (used, max string) {
	used = "N/A"
	max = "N/A"
	lines := strings.Split(info, "\r\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "used_memory_human:") {
			used = strings.TrimPrefix(line, "used_memory_human:")
		} else if strings.HasPrefix(line, "maxmemory_human:") {
			max = strings.TrimPrefix(line, "maxmemory_human:")
		}
	}
	// Redis might return maxmemory 0 for unlimited, but we will pass whatever it gives.
	return
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := redisClient.Ping(ctx).Err()
	status := "healthy"
	redisStatus := "connected"
	if err != nil {
		status = "degraded"
		redisStatus = "disconnected"
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":    status,
		"redis":     redisStatus,
		"timestamp": time.Now().Format(time.RFC3339),
	})
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
	metrics.Lock()
	defer metrics.Unlock()

	total := metrics.Hits + metrics.Misses
	var hitRate, avgHit, avgMiss float64
	if total > 0 {
		hitRate = float64(metrics.Hits) / float64(total) * 100
	}

	sum := 0.0
	for _, l := range metrics.HitLatencies {
		sum += l
	}
	if len(metrics.HitLatencies) > 0 {
		avgHit = sum / float64(len(metrics.HitLatencies))
	}

	sum = 0.0
	for _, l := range metrics.MissLatencies {
		sum += l
	}
	if len(metrics.MissLatencies) > 0 {
		avgMiss = sum / float64(len(metrics.MissLatencies))
	}

	elapsed := time.Since(metrics.StartTime).Seconds()
	
	reqPerSec := 0.0
	if elapsed > 0 {
		reqPerSec = float64(total) / elapsed
	}

	info, err := redisClient.Info(context.Background(), "memory").Result()
	usedMem, maxMem := "N/A", "N/A"
	if err == nil {
		usedMem, maxMem = parseRedisMemory(info)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"total_requests":       total,
		"total_hits":           metrics.Hits,
		"total_misses":         metrics.Misses,
		"hit_rate_percent":     hitRate,
		"avg_hit_latency_ms":   avgHit,
		"avg_miss_latency_ms":  avgMiss,
		"elapsed_seconds":      elapsed,
		"requests_per_second":  reqPerSec,
		"redis_used_memory":    usedMem,
		"redis_max_memory":     maxMem,
	})
}

func resetMetricsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	metrics.Lock()
	metrics.Hits = 0
	metrics.Misses = 0
	metrics.HitLatencies = nil
	metrics.MissLatencies = nil
	metrics.StartTime = time.Now()
	metrics.Unlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "metrics reset"})
}

func queryHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	start := time.Now()

	var req QueryRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	ctx := context.Background()
	cacheKey := fmt.Sprintf("question:%d", req.QuestionID)

	val, err := redisClient.Get(ctx, cacheKey).Result()
	if err == nil {
		// Cache Hit
		elapsed := time.Since(start).Seconds() * 1000
		metrics.Lock()
		metrics.Hits++
		metrics.HitLatencies = append(metrics.HitLatencies, elapsed)
		metrics.Unlock()

		go updateAccessCount(req.QuestionID)

		var cached map[string]interface{}
		json.Unmarshal([]byte(val), &cached)

		var llmAns *string
		var cosScore, rouScore *float64

		if a, ok := cached["llm_answer"].(string); ok {
			llmAns = &a
		}
		if c, ok := cached["cosine_score"].(float64); ok {
			cosScore = &c
		}
		if rs, ok := cached["rouge_score"].(float64); ok {
			rouScore = &rs
		}

		resp := QueryResponse{
			QuestionID:  req.QuestionID,
			Source:      "cache",
			LLMAnswer:   llmAns,
			CosineScore: cosScore,
			RougeScore:  rouScore,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
		return
	}

	// Cache Miss
	bodyBytes, _ := json.Marshal(req)
	httpReq, _ := http.NewRequestWithContext(ctx, "POST", scoreURL+"/evaluate", bytes.NewBuffer(bodyBytes))
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 60 * time.Second}
	httpResp, err := client.Do(httpReq)
	if err != nil {
		http.Error(w, "Score service unavailable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		bodyErr, _ := io.ReadAll(httpResp.Body)
		http.Error(w, string(bodyErr), http.StatusBadGateway)
		return
	}

	var scoreRes ScoreResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&scoreRes); err != nil {
		http.Error(w, "Error parsing score response", http.StatusInternalServerError)
		return
	}

	// Save to cache
	cacheVal, _ := json.Marshal(map[string]interface{}{
		"llm_answer":   scoreRes.LLMAnswerPreview,
		"cosine_score": scoreRes.CosineScore,
		"rouge_score":  scoreRes.RougeScore,
	})
	redisClient.Set(ctx, cacheKey, string(cacheVal), cacheTTL)

	go updateAccessCount(req.QuestionID)

	elapsed := time.Since(start).Seconds() * 1000
	metrics.Lock()
	metrics.Misses++
	metrics.MissLatencies = append(metrics.MissLatencies, elapsed)
	metrics.Unlock()

	resp := QueryResponse{
		QuestionID:  req.QuestionID,
		Source:      "llm",
		LLMAnswer:   &scoreRes.LLMAnswerPreview,
		CosineScore: &scoreRes.CosineScore,
		RougeScore:  &scoreRes.RougeScore,
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func updateAccessCount(id int) {
	if dbPool == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err := dbPool.Exec(ctx, "UPDATE questions SET access_count = access_count + 1 WHERE id = $1", id)
	if err != nil {
		log.Printf("Error updating access count for %d: %v", id, err)
	}
}

func main() {
	initEnv()

	// Wait for services indefinitely to prevent crashes during docker compose startup
	for {
		err := initDB(context.Background())
		if err == nil {
			log.Println("PostgreSQL connected")
			break
		}
		log.Printf("Waiting for DB: %v", err)
		time.Sleep(2 * time.Second)
	}

	for {
		err := initRedis(context.Background())
		if err == nil {
			log.Println("Redis connected")
			break
		}
		log.Printf("Waiting for Redis: %v", err)
		time.Sleep(2 * time.Second)
	}

	http.HandleFunc("/health", healthHandler)
	http.HandleFunc("/metrics", metricsHandler)
	http.HandleFunc("/metrics/reset", resetMetricsHandler)
	http.HandleFunc("/query", queryHandler)

	log.Println("Cache Service (Go Proxy) running on :8000")
	if err := http.ListenAndServe(":8000", nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
