package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type QueryRequest struct {
	QuestionID int `json:"question_id"`
}

var (
	cacheServiceURL = getEnv("CACHE_SERVICE_URL", "http://localhost:8000")
	distribution    = getEnv("DISTRIBUTION", "poisson")
	rate            = getEnvAsFloat("RATE", 10.0)
	totalRequests   = getEnvAsInt("TOTAL_REQUESTS", 500)
	seedLimit       = getEnvAsInt("SEED_LIMIT", 10000)
)

func getEnv(key, fallback string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return fallback
}

func getEnvAsInt(key string, fallback int) int {
	strValue := getEnv(key, "")
	if value, err := strconv.Atoi(strValue); err == nil {
		return value
	}
	return fallback
}

func getEnvAsFloat(key string, fallback float64) float64 {
	strValue := getEnv(key, "")
	if value, err := strconv.ParseFloat(strValue, 64); err == nil {
		return value
	}
	return fallback
}

// simulateRequest envía la consulta al Cache Service (Proxy)
func simulateRequest(questionID int, wg *sync.WaitGroup) {
	defer wg.Done()

	reqBody, _ := json.Marshal(QueryRequest{QuestionID: questionID})
	
	// Creamos un cliente con un timeout para evitar colgar goroutines
	client := &http.Client{Timeout: 60 * time.Second}
	
	resp, err := client.Post(cacheServiceURL+"/query", "application/json", bytes.NewBuffer(reqBody))
	if err != nil {
		log.Printf("Error de red al consultar caché para pregunta %d: %v", questionID, err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Error HTTP %d al consultar caché para pregunta %d", resp.StatusCode, questionID)
		return
	}
	
	// Aquí podríamos deserializar la respuesta si nos interesara imprimir el resultado
	// var qResp QueryResponse
	// json.NewDecoder(resp.Body).Decode(&qResp)
}

// Generador de tráfico con distribución de Poisson (intervalos exponenciales)
func generatePoissonTraffic(rate float64, total int, wg *sync.WaitGroup) {
	log.Printf("Iniciando tráfico Poisson (Tasa esperada: %.2f req/s, Total: %d)", rate, total)
	for i := 0; i < total; i++ {
		// Intervalo de tiempo inter-arribo (exponencial)
		interArrivalTime := time.Duration(float64(time.Second) * (1 / rate) * rand.ExpFloat64())
		time.Sleep(interArrivalTime)

		randomQID := rand.Intn(seedLimit) + 1
		wg.Add(1)
		go simulateRequest(randomQID, wg)
	}
}

// Generador de tráfico Constante
func generateConstantTraffic(rate float64, total int, wg *sync.WaitGroup) {
	log.Printf("Iniciando tráfico Constante (Tasa: %.2f req/s, Total: %d)", rate, total)
	delay := time.Duration(float64(time.Second) / rate)
	
	for i := 0; i < total; i++ {
		time.Sleep(delay)
		randomQID := rand.Intn(seedLimit) + 1
		wg.Add(1)
		go simulateRequest(randomQID, wg)
	}
}

// Generador de tráfico Zipf
func generateZipfTraffic(rate float64, total int, wg *sync.WaitGroup) {
	log.Printf("Iniciando tráfico Zipf (Tasa: %.2f req/s, Total: %d)", rate, total)
	
	// Parámetros para Zipf
	s := 1.1 // exponente > 1
	v := 1.0
	imax := uint64(seedLimit - 1)
	
	src := rand.NewSource(time.Now().UnixNano())
	r := rand.New(src)
	zipf := rand.NewZipf(r, s, v, imax)
	
	if zipf == nil {
		log.Fatal("Error inicializando distribución Zipf")
	}

	delay := time.Duration(float64(time.Second) / rate)
	
	for i := 0; i < total; i++ {
		time.Sleep(delay)
		
		// zipf genera valores de 0 a imax. Sumamos 1 porque nuestros IDs empiezan en 1
		randomQID := int(zipf.Uint64()) + 1
		
		wg.Add(1)
		go simulateRequest(randomQID, wg)
	}
}

func main() {
	rand.Seed(time.Now().UnixNano())

	fmt.Println("--- SISTEMA GENERADOR DE TRÁFICO ---")
	fmt.Printf("Configuración actual:\n")
	fmt.Printf("- CACHE_SERVICE: %s\n", cacheServiceURL)
	fmt.Printf("- DISTRIBUCION: %s\n", distribution)
	fmt.Printf("- TASA: %.2f req/s\n", rate)
	fmt.Printf("- TOTAL_REQUESTS: %d\n", totalRequests)
	fmt.Printf("- MAX_QUESTION_ID: %d\n", seedLimit)
	fmt.Println("------------------------------------")

	var wg sync.WaitGroup

	distLower := strings.ToLower(distribution)
	if distLower == "poisson" {
		generatePoissonTraffic(rate, totalRequests, &wg)
	} else if distLower == "zipf" {
		generateZipfTraffic(rate, totalRequests, &wg)
	} else if distLower == "constante" || distLower == "constant" {
		generateConstantTraffic(rate, totalRequests, &wg)
	} else {
		log.Fatalf("Distribución no soportada: %s", distribution)
	}

	log.Println("Generación completada. Esperando a que terminen los requests pendientes...")
	wg.Wait()
	log.Println("Todos los requests han finalizado.")
}
