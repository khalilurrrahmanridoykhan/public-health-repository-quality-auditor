CREATE TABLE audit_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repository TEXT NOT NULL,
  commit_sha TEXT,
  ran_at TEXT NOT NULL,
  score INTEGER NOT NULL,
  grade TEXT NOT NULL,
  passed INTEGER NOT NULL,
  source TEXT NOT NULL
);

CREATE INDEX idx_audit_runs_repository_ran_at ON audit_runs (repository, ran_at);
