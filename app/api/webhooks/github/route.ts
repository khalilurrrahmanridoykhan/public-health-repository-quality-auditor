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
  if (event !== "push") {
    return Response.json({ status: "ignored", event });
  }

  const payload = JSON.parse(body) as {
    deleted?: boolean;
    after?: string;
    installation?: { id?: number };
    repository?: { full_name?: string };
  };
  if (payload.deleted) {
    return Response.json({ status: "ignored", event: "deleted-ref" });
  }

  const installationId = payload.installation?.id;
  const repository = payload.repository?.full_name;
  const headSha = payload.after;
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
