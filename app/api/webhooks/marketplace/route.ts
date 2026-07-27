import { createHmac, timingSafeEqual } from "node:crypto";

export const runtime = "nodejs";

function verifyMarketplaceWebhook(body: string, signature: string | null) {
  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  if (!secret || !signature?.startsWith("sha256=")) return false;
  const expected = `sha256=${createHmac("sha256", secret)
    .update(body)
    .digest("hex")}`;
  const received = Buffer.from(signature);
  const calculated = Buffer.from(expected);
  return (
    received.length === calculated.length &&
    timingSafeEqual(received, calculated)
  );
}

export async function POST(request: Request) {
  const body = await request.text();
  if (
    !verifyMarketplaceWebhook(
      body,
      request.headers.get("x-hub-signature-256"),
    )
  ) {
    return Response.json({ error: "Invalid webhook signature" }, { status: 401 });
  }

  const event = request.headers.get("x-github-event");
  if (event === "ping") return Response.json({ status: "pong" });
  if (event !== "marketplace_purchase") {
    return Response.json({ status: "ignored", event });
  }

  const payload = JSON.parse(body) as {
    action?: string;
    marketplace_purchase?: {
      account?: { login?: string };
      plan?: { name?: string };
    };
  };
  return Response.json({
    status: "accepted",
    action: payload.action ?? "unknown",
    account: payload.marketplace_purchase?.account?.login ?? "unknown",
    plan: payload.marketplace_purchase?.plan?.name ?? "unknown",
  });
}
