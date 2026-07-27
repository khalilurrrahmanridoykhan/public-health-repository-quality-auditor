import hashlib
import hmac

from fastapi.testclient import TestClient

from ph_repo_auditor import webhook
from ph_repo_auditor.webhook import verify_signature


def test_signature_verification():
    body = b'{"zen":"Public health"}'
    signature = "sha256=" + hmac.new(
        b"secret", body, hashlib.sha256
    ).hexdigest()

    assert verify_signature("secret", body, signature)
    assert not verify_signature("wrong", body, signature)
    assert not verify_signature("secret", body, None)


def test_pull_request_payload_uses_head_sha(monkeypatch):
    calls: list[tuple[int, str, str]] = []

    class FakeClient:
        def audit(self, installation_id, repository, ref):
            calls.append((installation_id, repository, ref))
            from ph_repo_auditor.auditor import audit_repository

            return audit_repository(repository, {})

        def publish_check(self, installation_id, repository, head_sha, report):
            assert head_sha == "abc123"

    monkeypatch.setattr(webhook, "_client_from_environment", lambda: FakeClient())
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    payload = (
        b'{"action":"synchronize","installation":{"id":7},'
        b'"repository":{"full_name":"owner/repo"},'
        b'"pull_request":{"draft":false,"head":{"sha":"abc123"}}}'
    )
    signature = "sha256=" + hmac.new(
        b"secret", payload, hashlib.sha256
    ).hexdigest()
    response = TestClient(webhook.app).post(
        "/webhooks/github",
        content=payload,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-hub-signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert calls == [(7, "owner/repo", "abc123")]


def test_draft_pull_request_is_ignored(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    payload = (
        b'{"action":"opened","pull_request":{"draft":true},'
        b'"installation":{"id":7},"repository":{"full_name":"owner/repo"}}'
    )
    signature = "sha256=" + hmac.new(
        b"secret", payload, hashlib.sha256
    ).hexdigest()
    response = TestClient(webhook.app).post(
        "/webhooks/github",
        content=payload,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-hub-signature-256": signature,
        },
    )

    assert response.json() == {
        "status": "ignored",
        "event": "draft-pull-request",
    }
