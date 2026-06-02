CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    class_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    best_answer TEXT NOT NULL,
    llm_answer TEXT,
    score NUMERIC(5,4),        -- Similitud semántica (coseno) 
    rouge_score NUMERIC(5,4),  -- Similitud léxica (ROUGE-L)
    access_count INTEGER DEFAULT 0,   -- Contador de accesos (cache hits)
    processed_at TIMESTAMP           -- Timestamp de procesamiento por el LLM
);

-- Índices para consultas de análisis
CREATE INDEX idx_access_count ON questions(access_count);
CREATE INDEX idx_class_index ON questions(class_index);
CREATE INDEX idx_score ON questions(score);