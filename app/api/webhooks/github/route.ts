import { auditAndPublish, verifyWebhook } from "@/lib/github-app";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  const body = await request.text();
  if (!verifyWebhook(body, request.headers.get("x-hub-signature-256"))) {
    return Response.json({ error: "Invalid webhook signature" }, { status: 401 });
  }

  const event = request.headers.get("x-github-event");
  if (event === "ping") {
    return Response.json({ status: "pong" });
  }
  if (event !== "push" && event !== "pull_request") {
    return Response.json({ status: "ignored", event });
  }

  const payload = JSON.parse(body) as {
    action?: string;
    deleted?: boolean;
    after?: string;
    installation?: { id?: number };
    repository?: { full_name?: string };
    pull_request?: {
      draft?: boolean;
      head?: { sha?: string };
    };
  };
  if (event === "push" && payload.deleted) {
    return Response.json({ status: "ignored", event: "deleted-ref" });
  }
  if (event === "pull_request") {
    const auditedActions = new Set([
      "opened",
      "reopened",
      "synchronize",
      "ready_for_review",
    ]);
    if (!payload.action || !auditedActions.has(payload.action)) {
      return Response.json({
        status: "ignored",
        event: `pull_request.${payload.action ?? "unknown"}`,
      });
    }
    if (payload.pull_request?.draft) {
      return Response.json({ status: "ignored", event: "draft-pull-request" });
    }
  }

  const installationId = payload.installation?.id;
  const repository = payload.repository?.full_name;
  const headSha =
    event === "pull_request" ? payload.pull_request?.head?.sha : payload.after;
  if (!installationId || !repository || !headSha) {
    return Response.json(
      { error: "Missing installation, repository, or commit" },
      { status: 422 },
    );
  }

  const report = await auditAndPublish(
    installationId,
    repository,
    headSha,
  );
  return Response.json({ status: "completed", score: report.score });
}
