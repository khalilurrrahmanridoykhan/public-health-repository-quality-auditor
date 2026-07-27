import { createHmac, createPrivateKey, timingSafeEqual } from "node:crypto";
import { SignJWT } from "jose";
import { audit } from "./auditor";

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

async function appJwt() {
  const now = Math.floor(Date.now() / 1000);
  const key = createPrivateKey(requireEnvironment("GITHUB_PRIVATE_KEY"));
  return new SignJWT({})
    .setProtectedHeader({ alg: "RS256" })
    .setIssuedAt(now - 60)
    .setExpirationTime(now + 540)
    .setIssuer(requireEnvironment("GITHUB_APP_ID"))
    .sign(key);
}

async function installationToken(installationId: number) {
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

  for (const path of paths.filter((candidate) =>
    ["readme.md", "readme.rst"].includes(candidate.toLowerCase()),
  )) {
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

  const report = audit(repository, files);
  await githubFetch(`/repos/${repository}/check-runs`, token, {
    method: "POST",
    body: JSON.stringify({
      name: "Public Health Repository Quality",
      head_sha: headSha,
      status: "completed",
      conclusion: report.score >= 80 ? "success" : "neutral",
      output: {
        title: `Quality score: ${report.score}/100 (${report.grade})`,
        summary: report.markdown,
      },
    }),
    headers: { "Content-Type": "application/json" },
  });
  return report;
}
