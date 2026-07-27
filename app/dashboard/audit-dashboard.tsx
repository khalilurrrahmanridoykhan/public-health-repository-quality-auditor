"use client";

import { useEffect, useState } from "react";

type Repository = {
  fullName: string;
  defaultBranch: string;
  htmlUrl: string;
};

export function AuditDashboard() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/repositories")
      .then((response) => response.json())
      .then((payload) => {
        setRepositories(payload.repositories ?? []);
        if (payload.error) setMessage(payload.error);
      })
      .catch(() => setMessage("Could not load installed repositories."))
      .finally(() => setLoading(false));
  }, []);

  async function runAudit(repository: string) {
    setRunning(repository);
    setMessage("");
    try {
      const response = await fetch("/api/audits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Audit failed");
      setMessage(
        `${repository}: ${payload.score}/100 (${payload.grade}) — ${payload.passed ? "Pass" : "Needs work"}. The Check Run is now on GitHub.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Audit failed");
    } finally {
      setRunning(null);
    }
  }

  if (loading) return <p>Loading installed repositories…</p>;

  return (
    <>
      {message && <p className="dashboard-message">{message}</p>}
      <div className="repository-list">
        {repositories.map((repository) => (
          <article className="repository" key={repository.fullName}>
            <div>
              <a href={repository.htmlUrl}>{repository.fullName}</a>
              <small>Default branch: {repository.defaultBranch}</small>
            </div>
            <button
              disabled={running !== null}
              onClick={() => runAudit(repository.fullName)}
            >
              {running === repository.fullName ? "Auditing…" : "Run audit"}
            </button>
          </article>
        ))}
      </div>
      {!repositories.length && (
        <p>
          No public repositories are available. Install the GitHub App to get
          started.
        </p>
      )}
    </>
  );
}
