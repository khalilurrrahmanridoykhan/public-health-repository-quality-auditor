export const metadata = { title: "Privacy · Public Health Repo Auditor" };

export default function PrivacyPage() {
  return (
    <main className="legal">
      <p className="eyebrow">Public Health Repo Auditor</p>
      <h1>Privacy policy</h1>
      <p>Last updated: October 9, 2026</p>
      <h2>Data processed</h2>
      <p>
        The App reads repository metadata, file paths, and selected documentation
        needed to calculate repository-quality checks. It receives GitHub webhook
        payloads for configured repository events.
      </p>
      <h2>Data retention</h2>
      <p>
        Audit results are written to GitHub Check Runs. The hosted service does
        not maintain a database of repository content, file contents, audit
        findings text, or installation access tokens.
      </p>
      <p>
        A separate run-history database records, for trend and badge features,
        only: repository name, commit SHA, timestamp, numeric score, letter
        grade, pass/fail status, and which feature triggered the run (webhook,
        manual audit, org-wide audit, or the public demo). No file content, no
        finding details, and no personal or patient data are ever written to
        this database.
      </p>
      <h2>Private repositories</h2>
      <p>
        Private repository names and content are not displayed on the public
        dashboard. Access is limited by the permissions granted during GitHub
        App installation.
      </p>
      <h2>Contact</h2>
      <p>
        Privacy questions may be sent to{" "}
        <a href="mailto:khalilurrahmanridoykhan@gmail.com">
          khalilurrahmanridoykhan@gmail.com
        </a>.
      </p>
      <a href="/">Return home</a>
    </main>
  );
}
