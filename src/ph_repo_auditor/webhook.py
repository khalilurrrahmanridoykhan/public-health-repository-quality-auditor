from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request

from .github import GitHubAppClient, GitHubAppConfig


app = FastAPI(
    title="Public Health Repository Quality Auditor",
    version="0.1.0",
    docs_url="/docs",
)


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _client_from_environment() -> GitHubAppClient:
    app_id = os.environ.get("GITHUB_APP_ID", "")
    private_key = os.environ.get("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
    if not app_id or not private_key:
        raise HTTPException(503, "GitHub App credentials are not configured")
    return GitHubAppClient(GitHubAppConfig(app_id, private_key))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str | int]:
    body = await request.body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")

    if x_github_event == "ping":
        return {"status": "pong"}
    if x_github_event != "push":
        return {"status": "ignored", "event": x_github_event or "unknown"}

    payload = await request.json()
    if payload.get("deleted"):
        return {"status": "ignored", "event": "deleted-ref"}

    installation_id = payload.get("installation", {}).get("id")
    repository = payload.get("repository", {}).get("full_name")
    head_sha = payload.get("after")
    if not installation_id or not repository or not head_sha:
        raise HTTPException(422, "Webhook is missing installation, repository, or commit data")

    client = _client_from_environment()
    report = client.audit(installation_id, repository, head_sha)
    client.publish_check(installation_id, repository, head_sha, report)
    return {"status": "completed", "score": report.score}
