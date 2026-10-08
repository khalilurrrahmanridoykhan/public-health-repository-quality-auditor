"use client";

import { useEffect, useState } from "react";

type StoredRun = {
  id: number;
  ranAt: string;
  score: number;
  grade: string;
  passed: boolean;
  source: string;
};

export function TrendView({ repository }: { repository: string }) {
  const [runs, setRuns] = useState<StoredRun[] | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch(`/api/trend?repository=${encodeURIComponent(repository)}`)
      .then((response) => response.json() as Promise<{ runs?: StoredRun[]; error?: string }>)
      .then((payload) => {
        if (payload.error) {
          setMessage(payload.error);
          setRuns([]);
        } else {
          setRuns(payload.runs ?? []);
        }
      })
      .catch(() => setMessage("Could not load run history."));
  }, [repository]);

  if (runs === null) return <p>Loading trend…</p>;
  if (message) return <p className="dashboard-message">{message}</p>;
  if (runs.length === 0) {
    return (
      <p>
        No recorded runs yet for <code>{repository}</code>. Trend history
        starts accumulating once this repository is audited via a webhook
        push/PR, a manual dashboard audit, or an org-wide audit.
      </p>
    );
  }

  return (
    <>
      <div className="trend-bars">
        {runs.map((run) => (
          <div className="trend-bar-row" key={run.id}>
            <span className="trend-date">{run.ranAt.slice(0, 10)}</span>
            <div className="trend-bar-track">
              <div
                className="trend-bar-fill"
                style={{ width: `${run.score}%` }}
                title={`${run.score}/100 (${run.grade}) via ${run.source}`}
              />
            </div>
            <span className="trend-score">
              {run.score}/100 ({run.grade})
            </span>
          </div>
        ))}
      </div>
      <table className="org-audit-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Score</th>
            <th>Grade</th>
            <th>Status</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {[...runs].reverse().map((run) => (
            <tr key={run.id}>
              <td>{run.ranAt.replace("T", " ").slice(0, 19)}</td>
              <td>{run.score}/100</td>
              <td>{run.grade}</td>
              <td>{run.passed ? "Pass" : "Needs work"}</td>
              <td>{run.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
