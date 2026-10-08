import { auditOrganization } from "@/lib/github-app";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const org = searchParams.get("org")?.trim();
  const page = Number(searchParams.get("page") ?? "1");
  if (!org) {
    return Response.json({ error: "org is required" }, { status: 422 });
  }
  if (!Number.isInteger(page) || page < 1) {
    return Response.json({ error: "page must be a positive integer" }, { status: 422 });
  }

  try {
    const { results, nextPage } = await auditOrganization(org, page);
    return Response.json({ org, page, nextPage, results });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error ? error.message : "Could not audit organization",
      },
      { status: 400 },
    );
  }
}
