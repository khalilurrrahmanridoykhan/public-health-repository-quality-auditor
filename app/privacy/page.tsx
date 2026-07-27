export const metadata = { title: "Privacy · Public Health Repo Auditor" };

export default function PrivacyPage() {
  return (
    <main className="legal">
      <p className="eyebrow">Public Health Repo Auditor</p>
      <h1>Privacy policy</h1>
      <p>Last updated: July 27, 2026</p>
      <h2>Data processed</h2>
      <p>
        The App reads repository metadata, file paths, and selected documentation
        needed to calculate repository-quality checks. It receives GitHub webhook
        payloads for configured repository events.
      </p>
      <h2>Data retention</h2>
      <p>
        Audit results are written to GitHub Check Runs. The hosted service does
        not maintain a separate database of repository content or installation
        access tokens.
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
