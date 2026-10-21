CREATE TABLE audits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  dataset_name TEXT,
  total_records INTEGER,
  disparate_impact REAL,
  biased INTEGER,
  report TEXT
);

CREATE TABLE agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id INTEGER REFERENCES audits(id),
  agent_id TEXT,
  status TEXT,
  summary TEXT
);

CREATE TABLE group_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id INTEGER REFERENCES audits(id),
  group_name TEXT,
  approval REAL,
  sample_size INTEGER
);