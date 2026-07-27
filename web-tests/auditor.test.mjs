import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { audit, policyFromObject } from "../lib/auditor.ts";

test("webhook route enforces signature verification", () => {
  const source = readFileSync(
    new URL("../app/api/webhooks/github/route.ts", import.meta.url),
    "utf8",
  );
  assert.match(source, /verifyWebhook/);
  assert.match(source, /status: 401/);
  assert.match(source, /pull_request/);
  assert.match(source, /ready_for_review/);
});

test("GitHub App client uses installation tokens and check runs", () => {
  const source = readFileSync(
    new URL("../lib/github-app.ts", import.meta.url),
    "utf8",
  );
  assert.ok(source.includes("installations/${installationId}/access_tokens"));
  assert.match(source, /check-runs/);
  assert.match(source, /\.ph-repo-auditor\.yml/);
});

test("repository policy controls threshold, disabled checks, and required files", () => {
  const { policy, warnings } = policyFromObject({
    minimum_score: 95,
    disabled_checks: ["ethics"],
    required_files: ["CITATION.cff", "docs/protocol.md"],
    ignore_paths: ["generated"],
  });
  const report = audit(
    "owner/repo",
    new Map([
      ["README.md", "Data provenance. Privacy."],
      ["LICENSE", null],
      ["CITATION.cff", null],
      ["requirements.txt", null],
      ["Makefile", null],
      [".github/workflows/ci.yml", null],
      ["docs/codebook.md", null],
      ["generated/tests/test_fake.ts", null],
    ]),
    policy,
    warnings,
  );

  assert.deepEqual(warnings, []);
  assert.equal(report.minimumScore, 95);
  assert.deepEqual(report.missingRequiredFiles, ["docs/protocol.md"]);
  assert.equal(report.passed, false);
  assert.doesNotMatch(report.markdown, /Ethics statement/);
});

test("invalid policy values use safe defaults and produce warnings", () => {
  const { policy, warnings } = policyFromObject({
    minimum_score: 101,
    disabled_checks: ["unknown"],
    required_files: "CITATION.cff",
  });

  assert.equal(policy.minimumScore, 80);
  assert.deepEqual(policy.disabledChecks, []);
  assert.equal(warnings.length, 3);
});
