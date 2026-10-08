"use client";

import { useState } from "react";

type OrgAuditResult = {
  repository: string;
  htmlUrl: string;
  score?: number;
  grade?: string;
  passed?: boolean;
  error?: string;
};

type SortKey = "repository" | "score";

export function OrgAudit() {
  const [org, setOrg] = useState("");
  const [results, setResults] = useState<OrgAuditResult[]>([]);
  const [page, setPage] = useState(1);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [onlyFailing, setOnlyFailing] = useState(false);

  async function loadPage(targetOrg: string, targetPage: number) {
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(
        `/api/org-audit?org=${encodeURIComponent(targetOrg)}&page=${targetPage}`,
      );
      const payload = (await response.json()) as {
        results?: OrgAuditResult[];
        nextPage?: number | null;
        error?: string;
      };
      if (!response.ok) throw new Error(payload.error ?? "Audit failed");
      setResults((previous) =>
        targetPage === 1 ? payload.results ?? [] : [...previous, ...(payload.results ?? [])],
      );
      setNextPage(payload.nextPage ?? null);
      setPage(targetPage);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Audit failed");
    } finally {
      setLoading(false);
    }
  }

  function startAudit() {
    if (!org.trim()) return;
    setResults([]);
    setNextPage(null);
    void loadPage(org.trim(), 1);
  }

  const visible = results
    .filter((result) => !onlyFailing || (result.passed === false && !result.error))
    .sort((a, b) => {
      if (sortKey === "score") return (b.score ?? -1) - (a.score ?? -1);
      return a.repository.localeCompare(b.repository);
    });

  return (
    <>
      <form
        className="org-audit-form"
        onSubmit={(event) => {
          event.preventDefault();
          startAudit();
        }}
      >
        <input
          value={org}
          onChange={(event) => setOrg(event.target.value)}
          placeholder="GitHub org, e.g. openmrs"
          aria-label="GitHub organization"
        />
        <button type="submit" disabled={loading || !org.trim()}>
          {loading && page === 1 ? "Auditing…" : "Audit organization"}
        </button>
      </form>
      <p className="hint">
        Audits that org&apos;s public, non-fork, non-archived repositories —
        one page at a time (Workers caps subrequests per request, so large
        orgs load in batches via &quot;Load more&quot;). No GitHub App
        installation required.
      </p>
      {message && <p className="dashboard-message">{message}</p>}
      {results.length > 0 && (
        <>
          <div className="org-audit-controls">
            <label>
              Sort by{" "}
              <select
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value as SortKey)}
              >
                <option value="score">Score</option>
                <option value="repository">Repository</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={onlyFailing}
                onChange={(event) => setOnlyFailing(event.target.checked)}
              />{" "}
              Only below threshold
            </label>
          </div>
          <table className="org-audit-table">
            <thead>
              <tr>
                <th>Repository</th>
                <th>Score</th>
                <th>Grade</th>
                <th>Status</th>
                <th>Links</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((result) => (
                <tr key={result.repository}>
                  <td>
                    <a href={result.htmlUrl}>{result.repository}</a>
                  </td>
                  <td>{result.error ? "—" : `${result.score}/100`}</td>
                  <td>{result.error ? "—" : result.grade}</td>
                  <td>
                    {result.error
                      ? `Error: ${result.error}`
                      : result.passed
                        ? "Pass"
                        : "Needs work"}
                  </td>
                  <td>
                    <a href={`/dashboard/trend?repository=${encodeURIComponent(result.repository)}`}>
                      Trend
                    </a>
                    {" · "}
                    <a href={`/api/report?repository=${encodeURIComponent(result.repository)}`}>
                      Report
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {nextPage && (
            <button disabled={loading} onClick={() => loadPage(org.trim(), nextPage)}>
              {loading ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      )}
    </>
  );
}
