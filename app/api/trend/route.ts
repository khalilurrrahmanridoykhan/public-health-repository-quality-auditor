import { getDb, getTrend } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const repository = searchParams.get("repository")?.trim();
  if (!repository) {
    return Response.json({ error: "repository is required" }, { status: 422 });
  }

  const db = await getDb();
  if (!db) {
    return Response.json(
      { error: "Run history is not available on this deployment yet" },
      { status: 503 },
    );
  }
  const runs = await getTrend(db, repository);
  return Response.json({ repository, runs });
}
