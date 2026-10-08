import { TrendView } from "./trend-view";

export const metadata = { title: "Trend · Public Health Repo Auditor" };

export default async function TrendPage({
  searchParams,
}: {
  searchParams: Promise<{ repository?: string }>;
}) {
  const { repository } = await searchParams;

  return (
    <main>
      <section className="hero compact">
        <p className="eyebrow">Score over time</p>
        <h1>{repository ?? "No repository selected"}</h1>
        <div className="actions">
          <a className="secondary" href="/dashboard">
            Back to dashboard
          </a>
        </div>
      </section>
      <section className="card">
        {repository ? (
          <TrendView repository={repository} />
        ) : (
          <p>
            Add <code>?repository=owner/repo</code> to the URL, or get here
            from the organization audit table.
          </p>
        )}
      </section>
    </main>
  );
}
