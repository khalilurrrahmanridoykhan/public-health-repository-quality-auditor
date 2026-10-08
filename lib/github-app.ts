import { createHmac, createPrivateKey, timingSafeEqual } from "node:crypto";
import { SignJWT } from "jose";
import { parse } from "yaml";
import { audit, policyFromObject } from "./auditor";
import { getDb, recordRun, type RunSource } from "./db";

const apiRoot = "https://api.github.com";
const apiHeaders = {
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  "User-Agent": "ph-repo-auditor/0.1",
};

function requireEnvironment(name: string) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not configured`);
  }
  return value.replaceAll("\\n", "\n");
}

export async function appJwt() {
  const now = Math.floor(Date.now() / 1000);
  const key = createPrivateKey(requireEnvironment("GITHUB_PRIVATE_KEY"));
  return new SignJWT({})
    .setProtectedHeader({ alg: "RS256" })
    .setIssuedAt(now - 60)
    .setExpirationTime(now + 540)
    .setIssuer(requireEnvironment("GITHUB_APP_ID"))
    .sign(key);
}

export async function installationToken(installationId: number) {
  const response = await fetch(
    `${apiRoot}/app/installations/${installationId}/access_tokens`,
    {
      method: "POST",
      headers: {
        ...apiHeaders,
        Authorization: `Bearer ${await appJwt()}`,
      },
    },
  );
  if (!response.ok) {
    throw new Error(`Installation token failed: ${response.status}`);
  }
  const payload = (await response.json()) as { token: string };
  return payload.token;
}

export function verifyWebhook(body: string, signature: string | null) {
  if (!signature?.startsWith("sha256=")) return false;
  const expected = `sha256=${createHmac(
    "sha256",
    requireEnvironment("GITHUB_WEBHOOK_SECRET"),
  )
    .update(body)
    .digest("hex")}`;
  const receivedBuffer = Buffer.from(signature);
  const expectedBuffer = Buffer.from(expected);
  return (
    receivedBuffer.length === expectedBuffer.length &&
    timingSafeEqual(receivedBuffer, expectedBuffer)
  );
}

async function githubFetch(
  url: string,
  token: string,
  init: RequestInit = {},
) {
  const response = await fetch(`${apiRoot}${url}`, {
    ...init,
    headers: {
      ...apiHeaders,
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub API ${url} failed: ${response.status}`);
  }
  return response;
}

/** Like `githubFetch`, but for repositories the App has no installation
 * on — the org-wide fleet audit and the public demo both need to read
 * arbitrary public repositories, not just ones an owner installed the
 * App on. Works unauthenticated (60 requests/hour per IP); set
 * `GITHUB_READONLY_TOKEN` (a plain PAT, no special scopes needed for
 * public repo reads) to raise that to 5000/hour for real traffic. */
async function publicGithubFetch(url: string, init: RequestInit = {}) {
  const token = process.env.GITHUB_READONLY_TOKEN;
  const response = await fetch(`${apiRoot}${url}`, {
    ...init,
    headers: {
      ...apiHeaders,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub API ${url} failed: ${response.status}`);
  }
  return response;
}

/** Fetches a repository's tree at `headSha` plus README/policy content,
 * parses the policy, and runs `audit()` — the part of auditing that's
 * identical whether the caller has an App installation token (
 * `auditAndPublish`) or is reading a public repo with no installation
 * at all (`auditAnyPublicRepository`). `fetchFn` carries whichever
 * auth (or none) the caller has. */
/** Records a run for trend history, swallowing any failure — a missing
 * or unreachable D1 binding (no database provisioned yet, a transient
 * error) must never take down the actual audit it's recording. */
async function recordRunQuietly(
  repository: string,
  commitSha: string,
  report: { score: number; grade: string; passed: boolean },
  source: RunSource,
) {
  try {
    const db = await getDb();
    if (!db) return;
    await recordRun(db, {
      repository,
      commitSha,
      ranAt: new Date().toISOString(),
      score: report.score,
      grade: report.grade,
      passed: report.passed,
      source,
    });
  } catch {
    // Trend history is best-effort; the audit itself already succeeded.
  }
}

async function auditTreeAt(
  repository: string,
  headSha: string,
  fetchFn: (url: string) => Promise<Response>,
) {
  const treeResponse = await fetchFn(
    `/repos/${repository}/git/trees/${headSha}?recursive=1`,
  );
  const treePayload = (await treeResponse.json()) as {
    tree: { path: string; type: string }[];
  };
  const paths = treePayload.tree
    .filter((item) => item.type === "blob")
    .map((item) => item.path);
  const files = new Map<string, string | null>(
    paths.map((path) => [path, null]),
  );

  const selectedPaths = paths.filter((candidate) =>
    [
      "readme.md",
      "readme.rst",
      ".ph-repo-auditor.yml",
      ".ph-repo-auditor.yaml",
    ].includes(candidate.toLowerCase()),
  );
  for (const path of selectedPaths) {
    const contentResponse = await fetchFn(
      `/repos/${repository}/contents/${path}?ref=${headSha}`,
    );
    const contentPayload = (await contentResponse.json()) as {
      content?: string;
    };
    files.set(
      path,
      Buffer.from(contentPayload.content ?? "", "base64").toString("utf8"),
    );
  }

  const policyPath = selectedPaths.find((path) =>
    [".ph-repo-auditor.yml", ".ph-repo-auditor.yaml"].includes(
      path.toLowerCase(),
    ),
  );
  let policyResult = policyFromObject({});
  if (!policyPath) {
    policyResult = { ...policyResult, warnings: [] };
  } else {
    try {
      policyResult = policyFromObject(parse(files.get(policyPath) ?? ""));
    } catch (error) {
      policyResult = {
        ...policyResult,
        warnings: [
          `Could not parse \`${policyPath}\`: ${error instanceof Error ? error.message : "invalid YAML"}`,
        ],
      };
    }
  }

  const report = audit(
    repository,
    files,
    policyResult.policy,
    policyResult.warnings,
  );
  return { report, paths };
}

export async function auditAndPublish(
  installationId: number,
  repository: string,
  headSha: string,
  source: RunSource = "webhook",
) {
  const token = await installationToken(installationId);
  const { report, paths } = await auditTreeAt(repository, headSha, (url) =>
    githubFetch(url, token),
  );
  await recordRunQuietly(repository, headSha, report, source);
  let previousScore: number | null = null;
  try {
    const commitResponse = await githubFetch(
      `/repos/${repository}/commits/${headSha}`,
      token,
    );
    const commit = (await commitResponse.json()) as {
      parents?: { sha: string }[];
    };
    const parentSha = commit.parents?.[0]?.sha;
    if (parentSha) {
      const checksResponse = await githubFetch(
        `/repos/${repository}/commits/${parentSha}/check-runs?check_name=${encodeURIComponent("Public Health Repository Quality")}`,
        token,
      );
      const checks = (await checksResponse.json()) as {
        check_runs?: { output?: { title?: string } }[];
      };
      const match = checks.check_runs?.[0]?.output?.title?.match(
        /Quality score: (\d+)\/100/,
      );
      if (match) previousScore = Number(match[1]);
    }
  } catch {
    previousScore = null;
  }
  const delta =
    previousScore === null
      ? "\n\nPrevious audited commit: **not available**"
      : `\n\nScore change from previous audited commit: **${report.score - previousScore >= 0 ? "+" : ""}${report.score - previousScore}** (${previousScore} → ${report.score})`;
  const readmePath =
    paths.find((path) => ["readme.md", "readme.rst"].includes(path.toLowerCase())) ??
    paths[0];
  const MAX_ANNOTATIONS = 50;
  const annotatable = readmePath
    ? report.results.filter((result) => !result.passed)
    : [];
  const annotations = annotatable.slice(0, MAX_ANNOTATIONS).map((result) => ({
    path: readmePath,
    start_line: 1,
    end_line: 1,
    annotation_level: "warning",
    title: result.title,
    message: result.recommendation,
    raw_details: result.documentationUrl,
  }));
  const remaining = annotatable.length - annotations.length;
  const overflowNote =
    remaining > 0
      ? `\n\n_...and ${remaining} more finding(s) not shown as inline annotations._`
      : "";
  await githubFetch(`/repos/${repository}/check-runs`, token, {
    method: "POST",
    body: JSON.stringify({
      name: "Public Health Repository Quality",
      head_sha: headSha,
      status: "completed",
      conclusion: report.passed ? "success" : "failure",
      output: {
        title: `Quality score: ${report.score}/100 (${report.grade})`,
        summary: `${report.markdown}${delta}${overflowNote}`,
        annotations,
      },
    }),
    headers: { "Content-Type": "application/json" },
  });
  return report;
}

export async function listPublicInstalledRepositories() {
  const jwt = await appJwt();
  const installationsResponse = await githubFetch("/app/installations", jwt);
  const installations = (await installationsResponse.json()) as {
    id: number;
  }[];
  const repositories: {
    installationId: number;
    fullName: string;
    defaultBranch: string;
    htmlUrl: string;
  }[] = [];
  for (const installation of installations) {
    const token = await installationToken(installation.id);
    const response = await githubFetch(
      "/installation/repositories?per_page=100",
      token,
    );
    const payload = (await response.json()) as {
      repositories: {
        private: boolean;
        full_name: string;
        default_branch: string;
        html_url: string;
      }[];
    };
    repositories.push(
      ...payload.repositories
        .filter((repository) => !repository.private)
        .map((repository) => ({
          installationId: installation.id,
          fullName: repository.full_name,
          defaultBranch: repository.default_branch,
          htmlUrl: repository.html_url,
        })),
    );
  }
  return repositories.sort((a, b) => a.fullName.localeCompare(b.fullName));
}

export async function auditPublicRepository(repository: string) {
  const repositories = await listPublicInstalledRepositories();
  const selected = repositories.find((item) => item.fullName === repository);
  if (!selected) throw new Error("Repository is not a public App installation");
  const token = await installationToken(selected.installationId);
  const response = await githubFetch(
    `/repos/${selected.fullName}/commits/${encodeURIComponent(selected.defaultBranch)}`,
    token,
  );
  const commit = (await response.json()) as { sha: string };
  return auditAndPublish(
    selected.installationId,
    selected.fullName,
    commit.sha,
    "manual",
  );
}

/** Audits any public repository, with no GitHub App installation
 * required and no Check Run posted — the org-wide fleet audit and the
 * public demo both need to read repositories the maintainer never
 * installed this App on. Returns the report plus the commit it ran
 * against, so callers can record a trend-history row. */
export async function auditAnyPublicRepository(
  repository: string,
  source: RunSource = "demo",
) {
  const repoResponse = await publicGithubFetch(`/repos/${repository}`);
  const repoPayload = (await repoResponse.json()) as {
    default_branch: string;
  };
  const commitResponse = await publicGithubFetch(
    `/repos/${repository}/commits/${encodeURIComponent(repoPayload.default_branch)}`,
  );
  const commit = (await commitResponse.json()) as { sha: string };
  const { report } = await auditTreeAt(repository, commit.sha, publicGithubFetch);
  await recordRunQuietly(repository, commit.sha, report, source);
  return { report, commitSha: commit.sha };
}

/** The next page number from a GitHub API response's RFC 5988 `Link`
 * header, or `null` on the last page. */
function nextPageFromLinkHeader(response: Response): number | null {
  const header = response.headers.get("link");
  if (!header) return null;
  const next = header
    .split(",")
    .map((part) => part.trim())
    .find((part) => part.endsWith('rel="next"'));
  const match = next?.match(/[?&]page=(\d+)/);
  return match ? Number(match[1]) : null;
}

export type OrgPage = {
  repositories: { fullName: string; defaultBranch: string; htmlUrl: string }[];
  nextPage: number | null;
};

/** One page of an org's public, non-fork, non-archived repositories —
 * forks and archives are excluded because an org-wide fleet audit is
 * about the org's own maintained work, not its copies of other
 * people's repos or ones it no longer touches. */
export async function listOrgPublicRepositories(
  org: string,
  page = 1,
  perPage = 8,
): Promise<OrgPage> {
  const response = await publicGithubFetch(
    `/orgs/${encodeURIComponent(org)}/repos?type=public&per_page=${perPage}&page=${page}&sort=full_name`,
  );
  const payload = (await response.json()) as {
    fork: boolean;
    archived: boolean;
    full_name: string;
    default_branch: string;
    html_url: string;
  }[];
  return {
    repositories: payload
      .filter((repository) => !repository.fork && !repository.archived)
      .map((repository) => ({
        fullName: repository.full_name,
        defaultBranch: repository.default_branch,
        htmlUrl: repository.html_url,
      })),
    nextPage: nextPageFromLinkHeader(response),
  };
}

export type OrgAuditResult = {
  repository: string;
  htmlUrl: string;
  score: number;
  grade: string;
  passed: boolean;
  commitSha: string;
  error?: undefined;
};

export type OrgAuditFailure = {
  repository: string;
  htmlUrl: string;
  error: string;
};

/** Audits one page of an org's public repositories. `perPage` is kept
 * small by default (see `listOrgPublicRepositories`): each repository
 * takes ~4 GitHub API calls (repo info, commit, tree, README/policy
 * content), and Cloudflare Workers caps subrequests per request at 50
 * on the free tier — this is the "paginated... if large" the plan calls
 * for, not an arbitrary choice. One failed repository doesn't fail the
 * whole page; it's reported alongside the successes. */
export async function auditOrganization(
  org: string,
  page = 1,
): Promise<{
  results: (OrgAuditResult | OrgAuditFailure)[];
  nextPage: number | null;
}> {
  const { repositories, nextPage } = await listOrgPublicRepositories(org, page);
  const results = await Promise.all(
    repositories.map(async (repository): Promise<OrgAuditResult | OrgAuditFailure> => {
      try {
        const { report, commitSha } = await auditAnyPublicRepository(
          repository.fullName,
          "org-audit",
        );
        return {
          repository: repository.fullName,
          htmlUrl: repository.htmlUrl,
          score: report.score,
          grade: report.grade,
          passed: report.passed,
          commitSha,
        };
      } catch (error) {
        return {
          repository: repository.fullName,
          htmlUrl: repository.htmlUrl,
          error: error instanceof Error ? error.message : "Audit failed",
        };
      }
    }),
  );
  return { results, nextPage };
}
