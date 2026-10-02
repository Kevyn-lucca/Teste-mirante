CREATE TABLE IF NOT EXISTS modernization_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code TEXT NOT NULL,
    generated_code TEXT,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL CHECK (status IN ('sucesso', 'falha', 'parcial')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);