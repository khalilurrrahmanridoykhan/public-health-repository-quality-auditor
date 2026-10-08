import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import {
  recordRun,
  getTrend,
  getLatestRun,
  getLatestRunPerRepository,
} from "../lib/db.ts";

// A minimal D1Database-shaped wrapper over node:sqlite, real enough to
// exercise the actual SQL this module issues (not a hand-rolled fake that
// could quietly diverge from real SQLite semantics). Loads the real
// migration file so the test schema can't drift from production's.
function fakeD1() {
  const sqlite = new DatabaseSync(":memory:");
  const schema = readFileSync(
    new URL("../migrations/0001_create_audit_runs.sql", import.meta.url),
    "utf8",
  );
  sqlite.exec(schema);
  return {
    prepare(sql) {
      return {
        bind(...params) {
          return {
            async run() {
              sqlite.prepare(sql).run(...params);
            },
            async all() {
              return { results: sqlite.prepare(sql).all(...params) };
            },
            async first() {
              return sqlite.prepare(sql).get(...params) ?? null;
            },
          };
        },
      };
    },
  };
}

test("recordRun stores a run retrievable by getLatestRun", async () => {
  const db = fakeD1();
  await recordRun(db, {
    repository: "owner/repo",
    commitSha: "abc123",
    ranAt: "2026-01-01T00:00:00Z",
    score: 90,
    grade: "A",
    passed: true,
    source: "webhook",
  });

  const latest = await getLatestRun(db, "owner/repo");
  assert.ok(latest);
  assert.equal(latest.repository, "owner/repo");
  assert.equal(latest.commitSha, "abc123");
  assert.equal(latest.score, 90);
  assert.equal(latest.grade, "A");
  assert.equal(latest.passed, true);
  assert.equal(latest.source, "webhook");
});

test("getLatestRun returns null for a repository with no runs", async () => {
  const db = fakeD1();
  assert.equal(await getLatestRun(db, "owner/never-audited"), null);
});

test("getLatestRun picks the most recent run by ran_at, not insertion order", async () => {
  const db = fakeD1();
  await recordRun(db, {
    repository: "owner/repo",
    commitSha: "newer",
    ranAt: "2026-01-02T00:00:00Z",
    score: 95,
    grade: "A",
    passed: true,
    source: "manual",
  });
  await recordRun(db, {
    repository: "owner/repo",
    commitSha: "older",
    ranAt: "2026-01-01T00:00:00Z",
    score: 70,
    grade: "C",
    passed: false,
    source: "webhook",
  });

  const latest = await getLatestRun(db, "owner/repo");
  assert.equal(latest?.commitSha, "newer");
});

test("getTrend returns a repository's runs oldest-first, capped at limit", async () => {
  const db = fakeD1();
  for (let i = 0; i < 5; i += 1) {
    await recordRun(db, {
      repository: "owner/repo",
      commitSha: `sha-${i}`,
      ranAt: `2026-01-0${i + 1}T00:00:00Z`,
      score: 60 + i * 5,
      grade: "C",
      passed: false,
      source: "webhook",
    });
  }

  const trend = await getTrend(db, "owner/repo", 3);
  assert.equal(trend.length, 3);
  // Oldest-first (chart order) among the 3 most recent runs.
  assert.deepEqual(
    trend.map((run) => run.commitSha),
    ["sha-2", "sha-3", "sha-4"],
  );
  assert.ok(trend[0].ranAt < trend[1].ranAt);
});

test("getTrend does not mix runs from different repositories", async () => {
  const db = fakeD1();
  await recordRun(db, {
    repository: "owner/a",
    commitSha: "a1",
    ranAt: "2026-01-01T00:00:00Z",
    score: 80,
    grade: "B",
    passed: true,
    source: "webhook",
  });
  await recordRun(db, {
    repository: "owner/b",
    commitSha: "b1",
    ranAt: "2026-01-01T00:00:00Z",
    score: 50,
    grade: "F",
    passed: false,
    source: "webhook",
  });

  const trend = await getTrend(db, "owner/a");
  assert.equal(trend.length, 1);
  assert.equal(trend[0].repository, "owner/a");
});

test("getLatestRunPerRepository returns one row per repository, the most recent", async () => {
  const db = fakeD1();
  await recordRun(db, {
    repository: "owner/a",
    commitSha: "a-old",
    ranAt: "2026-01-01T00:00:00Z",
    score: 60,
    grade: "D",
    passed: false,
    source: "org-audit",
  });
  await recordRun(db, {
    repository: "owner/a",
    commitSha: "a-new",
    ranAt: "2026-01-02T00:00:00Z",
    score: 85,
    grade: "B",
    passed: true,
    source: "org-audit",
  });
  await recordRun(db, {
    repository: "owner/b",
    commitSha: "b-only",
    ranAt: "2026-01-01T00:00:00Z",
    score: 40,
    grade: "F",
    passed: false,
    source: "org-audit",
  });

  const byRepository = await getLatestRunPerRepository(db, [
    "owner/a",
    "owner/b",
    "owner/never-audited",
  ]);
  assert.equal(byRepository.size, 2);
  assert.equal(byRepository.get("owner/a")?.commitSha, "a-new");
  assert.equal(byRepository.get("owner/b")?.commitSha, "b-only");
  assert.equal(byRepository.has("owner/never-audited"), false);
});

test("getLatestRunPerRepository returns an empty map for no repositories", async () => {
  const db = fakeD1();
  const byRepository = await getLatestRunPerRepository(db, []);
  assert.equal(byRepository.size, 0);
});
