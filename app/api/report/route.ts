import { auditAnyPublicRepository } from "@/lib/github-app";

export const runtime = "nodejs";
export const maxDuration = 60;

// PDF export is deferred — Workers have no headless-Chrome equivalent
// without Cloudflare's separate Browser Rendering product. Markdown is
// still a real, attachable conformance report (DPG/Digital Square
// submissions accept it) and needs no new infrastructure.
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const repository = searchParams.get("repository")?.trim();
  if (!repository) {
    return Response.json({ error: "repository is required" }, { status: 422 });
  }

  try {
    const { report } = await auditAnyPublicRepository(repository, "manual");
    const filename = `${repository.replace("/", "-")}-ph-repo-quality-report.md`;
    return new Response(report.markdown, {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error ? error.message : "Could not generate report",
      },
      { status: 400 },
    );
  }
}
