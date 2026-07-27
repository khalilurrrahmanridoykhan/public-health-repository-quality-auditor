import { listPublicInstalledRepositories } from "@/lib/github-app";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const repositories = await listPublicInstalledRepositories();
    return Response.json({
      repositories: repositories.map(({ installationId: _, ...repository }) =>
        repository,
      ),
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Could not load installed repositories",
      },
      { status: 500 },
    );
  }
}
