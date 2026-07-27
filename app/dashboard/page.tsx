import { AuditDashboard } from "./audit-dashboard";

export const metadata = { title: "Dashboard · Public Health Repo Auditor" };

export default function DashboardPage() {
  return (
    <main>
      <section className="hero compact">
        <p className="eyebrow">Onboarding dashboard</p>
        <h1>Installed repositories</h1>
        <p className="lede">
          Run an audit on any public repository connected to the GitHub App.
          Results are published as GitHub Check Runs.
        </p>
        <div className="actions">
          <a href="https://github.com/apps/public-health-repo-auditor/installations/new">
            Install the App
          </a>
          <a className="secondary" href="/">
            Home
          </a>
        </div>
      </section>
      <section className="card">
        <AuditDashboard />
      </section>
    </main>
  );
}
