CREATE TABLE audits (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW(),
  dataset_name TEXT,
  total_records INTEGER,
  disparate_impact REAL,
  biased BOOLEAN,
  report TEXT
);

CREATE TABLE agent_runs (
  id SERIAL PRIMARY KEY,
  audit_id INTEGER REFERENCES audits(id),
  agent_id TEXT,
  status TEXT,
  summary TEXT
);

CREATE TABLE group_results (
  id SERIAL PRIMARY KEY,
  audit_id INTEGER REFERENCES audits(id),
  group_name TEXT,
  approval REAL,
  sample_size INTEGER
);