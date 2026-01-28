-- Add API token domains relationship table
-- Run this script directly: psql -U your_user -d your_db -f add_api_token_domains.sql

CREATE TABLE IF NOT EXISTS api_token_domains (
    api_token_id INTEGER NOT NULL,
    domain_id INTEGER NOT NULL,
    PRIMARY KEY (api_token_id, domain_id),
    FOREIGN KEY (api_token_id) REFERENCES api_tokens(id) ON DELETE CASCADE,
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS ix_api_token_domains_api_token_id ON api_token_domains(api_token_id);
CREATE INDEX IF NOT EXISTS ix_api_token_domains_domain_id ON api_token_domains(domain_id);
