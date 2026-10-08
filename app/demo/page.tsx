import { auditAnyPublicRepository } from "@/lib/github-app";
import { getDb, getLatestRun } from "@/lib/db";

export const metadata = { title: "Live demo · Public Health Repo Auditor" };
export const runtime = "nodejs";
// force-dynamic, not a `revalidate` export: a `revalidate` number without
// this would make Next.js prerender the page — and run every curated
// repo's live GitHub calls — during `next build`, i.e. on every CI run
// and every deploy, not just real visits. Caching for real visitors
// instead comes from D1 below (reuse a stored run under an hour old),
// which doesn't run at build time since the D1 binding isn't available
// there (getDb() degrades to null, same as any other deployment that
// hasn't provisioned the database yet).
export const dynamic = "force-dynamic";

const CACHE_WINDOW_MS = 60 * 60 * 1000;

// Real, independently-maintained global goods this auditor was verified
// against during Phases 2 and 4 (not the maintainer's own repos — this
// page's whole point is showing the tool against widely-used digital
// health software, not a portfolio of one person's projects).
const CURATED_REPOSITORIES = [
  {
    repository: "HL7/fhir-ips",
    description: "HL7 International Patient Summary Implementation Guide",
  },
  {
    repository: "HL7/US-Core",
    description: "HL7 US Core Implementation Guide",
  },
  {
    repository: "openmrs/openmrs-module-idgen",
    description: "OpenMRS identifier-generation module",
  },
  {
    repository: "openmrs/openmrs-esm-patient-registration",
    description: "OpenMRS O3 patient-registration microfrontend",
  },
];

type DemoResult = {
  repository: string;
  description: string;
  score?: number;
  grade?: string;
  passed?: boolean;
  error?: string;
};

async function auditCuratedRepositories(): Promise<DemoResult[]> {
  const db = await getDb();
  return Promise.all(
    CURATED_REPOSITORIES.map(async ({ repository, description }) => {
      if (db) {
        const cached = await getLatestRun(db, repository);
        if (cached && Date.now() - Date.parse(cached.ranAt) < CACHE_WINDOW_MS) {
          return {
            repository,
            description,
            score: cached.score,
            grade: cached.grade,
            passed: cached.passed,
          };
        }
      }
      try {
        const { report } = await auditAnyPublicRepository(repository, "demo");
        return {
          repository,
          description,
          score: report.score,
          grade: report.grade,
          passed: report.passed,
        };
      } catch (error) {
        return {
          repository,
          description,
          error: error instanceof Error ? error.message : "Audit failed",
        };
      }
    }),
  );
}

export default async function DemoPage() {
  const results = await auditCuratedRepositories();

  return (
    <main>
      <section className="hero compact">
        <p className="eyebrow">Live, read-only demo</p>
        <h1>Real global goods, audited live</h1>
        <p className="lede">
          The hygiene checks (documentation, license, citation, tests,
          privacy, ...) run live against real digital-health
          implementation guides and modules on every visit — nothing
          here is seeded or faked. Updated at most once an hour.
        </p>
      </section>
      <section className="card">
        <table className="org-audit-table">
          <thead>
            <tr>
              <th>Repository</th>
              <th>Score</th>
              <th>Grade</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr key={result.repository}>
                <td>
                  <a href={`https://github.com/${result.repository}`}>
                    {result.repository}
                  </a>
                  <small>{result.description}</small>
                </td>
                <td>{result.error ? "—" : `${result.score}/100`}</td>
                <td>{result.error ? "—" : result.grade}</td>
                <td>
                  {result.error
                    ? `Unavailable: ${result.error}`
                    : result.passed
                      ? "Pass"
                      : "Needs work"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="hint">
          This is the hosted service&apos;s hygiene score only — the same 10
          research-reproducibility checks (citation file, dependency
          manifest, one-command reproduction, data dictionary, ...) every
          repository gets, whether it&apos;s a research study or, like
          these four, a published implementation guide or software
          module. Low scores here don&apos;t mean these are poor-quality
          projects — a FHIR IG genuinely has no &quot;data dictionary&quot;
          in that sense — they mean this checklist wasn&apos;t built for
          this repository shape. The CLI&apos;s platform-specific packs
          (FHIR/DHIS2/OpenMRS/PII/migration-safety/portability), which
          this Worker doesn&apos;t run yet, are what actually caught real,
          relevant findings in these exact repositories during
          development — see the README&apos;s pack sections.
        </p>
      </section>
    </main>
  );
}
