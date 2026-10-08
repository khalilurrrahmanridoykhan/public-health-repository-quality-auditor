import { getCloudflareContext } from "@opennextjs/cloudflare";

export type RunSource = "webhook" | "manual" | "org-audit" | "demo";

export type AuditRunRecord = {
  repository: string;
  commitSha: string | null;
  ranAt: string;
  score: number;
  grade: string;
  passed: boolean;
  source: RunSource;
};

export type StoredRun = AuditRunRecord & { id: number };

type AuditRunRow = {
  id: number;
  repository: string;
  commit_sha: string | null;
  ran_at: string;
  score: number;
  grade: string;
  passed: number;
  source: string;
};

function fromRow(row: AuditRunRow): StoredRun {
  return {
    id: row.id,
    repository: row.repository,
    commitSha: row.commit_sha,
    ranAt: row.ran_at,
    score: row.score,
    grade: row.grade,
    passed: row.passed === 1,
    source: row.source as RunSource,
  };
}

/** The `DB` binding declared in wrangler.jsonc, or `null` if this
 * deployment hasn't provisioned/bound a real D1 database yet (the
 * placeholder `database_id` in wrangler.jsonc still works for local dev
 * via `wrangler d1 migrations apply DB --local`, but a fresh checkout
 * with no binding at all — e.g. `next dev` without Cloudflare context —
 * has none). Callers degrade gracefully rather than throwing, same
 * policy as the Python core's optional external validators. */
export async function getDb(): Promise<D1Database | null> {
  try {
    const { env } = await getCloudflareContext({ async: true });
    return env.DB ?? null;
  } catch {
    return null;
  }
}

export async function recordRun(
  db: D1Database,
  run: AuditRunRecord,
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO audit_runs
         (repository, commit_sha, ran_at, score, grade, passed, source)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      run.repository,
      run.commitSha,
      run.ranAt,
      run.score,
      run.grade,
      run.passed ? 1 : 0,
      run.source,
    )
    .run();
}

/** Audit history for `repository`, oldest first (chart-ready order),
 * capped at `limit` most recent runs. */
export async function getTrend(
  db: D1Database,
  repository: string,
  limit = 50,
): Promise<StoredRun[]> {
  const { results } = await db
    .prepare(
      `SELECT * FROM audit_runs
       WHERE repository = ?
       ORDER BY ran_at DESC
       LIMIT ?`,
    )
    .bind(repository, limit)
    .all<AuditRunRow>();
  return results.map(fromRow).reverse();
}

export async function getLatestRun(
  db: D1Database,
  repository: string,
): Promise<StoredRun | null> {
  const row = await db
    .prepare(
      `SELECT * FROM audit_runs
       WHERE repository = ?
       ORDER BY ran_at DESC
       LIMIT 1`,
    )
    .bind(repository)
    .first<AuditRunRow>();
  return row ? fromRow(row) : null;
}

/** The latest run for every repository that has at least one, most
 * recently audited first — the backing data for an org/fleet table. */
export async function getLatestRunPerRepository(
  db: D1Database,
  repositories: string[],
): Promise<Map<string, StoredRun>> {
  if (repositories.length === 0) return new Map();
  const placeholders = repositories.map(() => "?").join(", ");
  const { results } = await db
    .prepare(
      `SELECT a.* FROM audit_runs a
       WHERE a.repository IN (${placeholders})
         AND a.ran_at = (
           SELECT MAX(b.ran_at) FROM audit_runs b
           WHERE b.repository = a.repository
         )`,
    )
    .bind(...repositories)
    .all<AuditRunRow>();
  const byRepository = new Map<string, StoredRun>();
  for (const row of results) {
    byRepository.set(row.repository, fromRow(row));
  }
  return byRepository;
}
