import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.github import GitHubAppClient, GitHubAppConfig


@pytest.fixture
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _client(private_key_pem: str, capture: dict) -> GitHubAppClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(200, json={"token": "installation-token"})
        if request.url.path.endswith("/check-runs"):
            capture["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 1})
        raise AssertionError(f"unexpected request: {request.url}")

    return GitHubAppClient(
        GitHubAppConfig(app_id="1", private_key=private_key_pem),
        transport=httpx.MockTransport(handler),
    )


def test_publish_check_sends_capped_annotations_with_a_note(private_key_pem):
    # 60 failing hygiene-like findings via the stub pack, well over the cap.
    from ph_repo_auditor.models import Finding
    from ph_repo_auditor.packs import PackRegistry, HygienePack

    class ManyFindingsPack:
        id = "stub"

        def detect(self, repo):
            return 1.0

        def run(self, repo, policy):
            return [
                Finding(
                    rule_id=f"stub/finding-{i}",
                    pack="stub",
                    severity="error",
                    category="stub",
                    title=f"Finding {i}",
                    message="stub message",
                    file="README.md",
                    line=i + 1,
                )
                for i in range(60)
            ]

    report = audit_repository(
        "owner/repo",
        {},
        registry=PackRegistry((HygienePack(), ManyFindingsPack())),
    )
    assert len(report.findings) > 50

    capture: dict = {}
    client = _client(private_key_pem, capture)
    client.publish_check(installation_id=1, repository="owner/repo", head_sha="sha", report=report)

    body = capture["body"]
    annotations = body["output"]["annotations"]
    assert len(annotations) == 50
    assert all(a["annotation_level"] == "failure" for a in annotations)
    assert "more finding(s) not shown as inline annotations" in body["output"]["summary"]


def test_publish_check_maps_severity_to_annotation_level(private_key_pem):
    from ph_repo_auditor.models import Finding
    from ph_repo_auditor.packs import PackRegistry, HygienePack

    class OneFindingPack:
        id = "stub"

        def detect(self, repo):
            return 1.0

        def run(self, repo, policy):
            return [
                Finding(
                    rule_id="stub/info-finding",
                    pack="stub",
                    severity="info",
                    category="stub",
                    title="Info finding",
                    message="informational",
                    file="README.md",
                    line=3,
                )
            ]

    report = audit_repository(
        "owner/repo",
        {},
        registry=PackRegistry((HygienePack(), OneFindingPack())),
    )
    capture: dict = {}
    client = _client(private_key_pem, capture)
    client.publish_check(installation_id=1, repository="owner/repo", head_sha="sha", report=report)

    annotations = capture["body"]["output"]["annotations"]
    info_annotation = next(a for a in annotations if a["title"] == "Info finding")
    assert info_annotation["annotation_level"] == "notice"
    assert info_annotation["start_line"] == 3


def test_publish_check_omits_findings_with_no_file_from_annotations(private_key_pem):
    # An empty repo: every hygiene finding has file=None (no README to anchor to).
    report = audit_repository("owner/empty", {})
    capture: dict = {}
    client = _client(private_key_pem, capture)
    client.publish_check(installation_id=1, repository="owner/empty", head_sha="sha", report=report)

    assert capture["body"]["output"]["annotations"] == []
