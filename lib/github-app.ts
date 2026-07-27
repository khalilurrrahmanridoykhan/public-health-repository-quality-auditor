import { createHmac, createPrivateKey, timingSafeEqual } from "node:crypto";
import { SignJWT } from "jose";
import { parse } from "yaml";
import { audit, policyFromObject } from "./auditor";

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

export async function auditAndPublish(
  installationId: number,
  repository: string,
  headSha: string,
) {
  const token = await installationToken(installationId);
  const treeResponse = await githubFetch(
    `/repos/${repository}/git/trees/${headSha}?recursive=1`,
    token,
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
    const contentResponse = await githubFetch(
      `/repos/${repository}/contents/${path}?ref=${headSha}`,
      token,
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
    selectedPaths.find((path) =>
      ["readme.md", "readme.rst"].includes(path.toLowerCase()),
    ) ?? paths[0];
  const annotations = report.results
    .filter((result) => !result.passed && readmePath)
    .slice(0, 50)
    .map((result) => ({
      path: readmePath,
      start_line: 1,
      end_line: 1,
      annotation_level: "warning",
      title: result.title,
      message: result.recommendation,
      raw_details: result.documentationUrl,
    }));
  await githubFetch(`/repos/${repository}/check-runs`, token, {
    method: "POST",
    body: JSON.stringify({
      name: "Public Health Repository Quality",
      head_sha: headSha,
      status: "completed",
      conclusion: report.passed ? "success" : "failure",
      output: {
        title: `Quality score: ${report.score}/100 (${report.grade})`,
        summary: `${report.markdown}${delta}`,
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
  );
}
