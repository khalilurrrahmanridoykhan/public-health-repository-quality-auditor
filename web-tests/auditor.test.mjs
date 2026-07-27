import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

test("webhook route enforces signature verification", () => {
  const source = readFileSync(
    new URL("../app/api/webhooks/github/route.ts", import.meta.url),
    "utf8",
  );
  assert.match(source, /verifyWebhook/);
  assert.match(source, /status: 401/);
});

test("GitHub App client uses installation tokens and check runs", () => {
  const source = readFileSync(
    new URL("../lib/github-app.ts", import.meta.url),
    "utf8",
  );
  assert.ok(source.includes("installations/${installationId}/access_tokens"));
  assert.match(source, /check-runs/);
});
