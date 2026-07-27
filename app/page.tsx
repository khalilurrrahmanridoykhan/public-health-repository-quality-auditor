const checks = [
  "Project documentation",
  "License and citation",
  "Dependency specification",
  "One-command reproduction",
  "Automated tests and CI",
  "Data dictionary",
  "Data provenance",
  "Privacy and ethics statements",
];

export default function Home() {
  return (
    <main>
      <section className="hero">
        <p className="eyebrow">GitHub App · Public-health research</p>
        <h1>Public Health Repo Auditor</h1>
        <p className="lede">
          Automated, transparent repository checks that help research teams
          improve reproducibility, documentation, and responsible data use.
        </p>
        <div className="actions">
          <a href="https://github.com/apps/public-health-repo-auditor">
            View GitHub App
          </a>
          <a
            className="secondary"
            href="https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor"
          >
            Source code
          </a>
        </div>
      </section>

      <section className="card">
        <h2>What it reviews</h2>
        <div className="grid">
          {checks.map((check) => (
            <div className="check" key={check}>
              <span aria-hidden="true">✓</span>
              {check}
            </div>
          ))}
        </div>
      </section>

      <section className="notice">
        <strong>Responsible use</strong>
        <p>
          The score supports maintainers. It does not certify scientific
          validity, regulatory compliance, privacy compliance, or research
          ethics.
        </p>
      </section>
    </main>
  );
}
