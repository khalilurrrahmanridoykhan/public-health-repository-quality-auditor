import { getDb, getLatestRun } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// https://shields.io/badges/endpoint-badge
const GRADE_COLORS: Record<string, string> = {
  A: "brightgreen",
  B: "green",
  C: "yellow",
  D: "orange",
  F: "red",
};

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const repository = searchParams.get("repository")?.trim();
  if (!repository) {
    return Response.json({ error: "repository is required" }, { status: 422 });
  }

  const db = await getDb();
  const run = db ? await getLatestRun(db, repository) : null;
  if (!run) {
    return Response.json({
      schemaVersion: 1,
      label: "PH repo quality",
      message: "not yet audited",
      color: "lightgrey",
    });
  }

  return Response.json({
    schemaVersion: 1,
    label: "PH repo quality",
    message: `${run.score}/100 (${run.grade})`,
    color: GRADE_COLORS[run.grade] ?? "lightgrey",
  });
}
