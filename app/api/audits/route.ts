import { auditPublicRepository } from "@/lib/github-app";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { repository?: string };
    if (!body.repository) {
      return Response.json({ error: "Repository is required" }, { status: 422 });
    }
    const report = await auditPublicRepository(body.repository);
    return Response.json({
      repository: report.repository,
      score: report.score,
      grade: report.grade,
      passed: report.passed,
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error ? error.message : "Could not run repository audit",
      },
      { status: 400 },
    );
  }
}
