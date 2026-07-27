export const metadata = { title: "Support · Public Health Repo Auditor" };

export default function SupportPage() {
  return (
    <main className="legal">
      <p className="eyebrow">Public Health Repo Auditor</p>
      <h1>Support</h1>
      <p>
        For installation help, audit questions, bug reports, or feature
        requests, open a GitHub issue. Include the repository URL, Check Run URL,
        expected result, and observed result, but never include private keys,
        access tokens, webhook secrets, or sensitive health data.
      </p>
      <div className="actions">
        <a href="https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/issues/new">
          Open a support issue
        </a>
        <a className="secondary" href="mailto:khalilurrahmanridoykhan@gmail.com">
          Email support
        </a>
      </div>
      <a href="/">Return home</a>
    </main>
  );
}
