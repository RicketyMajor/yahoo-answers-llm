CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    class_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    best_answer TEXT NOT NULL,
    llm_answer TEXT,
    score NUMERIC(5,4), -- Almacena la métrica de calidad 
    access_count INTEGER DEFAULT 0 -- Contador para los cache hits/misses
);

-- Crear un índice sobre access_count puede ser útil luego para analizar 
-- qué preguntas fueron las más consultadas por el generador de tráfico.
CREATE INDEX idx_access_count ON questions(access_count);