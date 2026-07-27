export const metadata = { title: "Terms · Public Health Repo Auditor" };

export default function TermsPage() {
  return (
    <main className="legal">
      <p className="eyebrow">Public Health Repo Auditor</p>
      <h1>Terms of service</h1>
      <p>Last updated: July 27, 2026</p>
      <h2>Purpose</h2>
      <p>
        The service provides automated repository-quality guidance. Scores do
        not certify scientific validity, legal compliance, privacy compliance,
        security, or research ethics.
      </p>
      <h2>Acceptable use</h2>
      <p>
        Do not use the service to rank researchers or institutions, process
        unlawfully obtained data, or replace qualified scientific, ethical,
        privacy, security, or legal review.
      </p>
      <h2>Availability and warranty</h2>
      <p>
        The service is provided as-is without guarantees of uninterrupted
        availability or completeness. Maintainers remain responsible for
        reviewing recommendations before acting on them.
      </p>
      <h2>Contact</h2>
      <p>
        Questions may be submitted through the project’s{" "}
        <a href="https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/issues">
          GitHub issue tracker
        </a>.
      </p>
      <a href="/">Return home</a>
    </main>
  );
}
