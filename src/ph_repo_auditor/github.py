from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx
import jwt

from .auditor import audit_repository
from .models import AuditReport
from .policy import parse_policy


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    private_key: str


class GitHubAppClient:
    def __init__(self, config: GitHubAppConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._client = httpx.Client(
            base_url=API_ROOT,
            timeout=30,
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "ph-repo-auditor/0.1",
            },
        )

    def _app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.config.app_id},
            self.config.private_key,
            algorithm="RS256",
        )

    def installation_token(self, installation_id: int) -> str:
        response = self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
        )
        response.raise_for_status()
        return response.json()["token"]

    def _installation_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def audit(self, installation_id: int, repository: str, ref: str) -> AuditReport:
        token = self.installation_token(installation_id)
        headers = self._installation_headers(token)
        tree_response = self._client.get(
            f"/repos/{repository}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=headers,
        )
        tree_response.raise_for_status()
        file_paths = [
            item["path"]
            for item in tree_response.json().get("tree", [])
            if item.get("type") == "blob"
        ]

        selected = {
            path
            for path in file_paths
            if path.lower() in {"readme.md", "readme.rst"}
            or path.lower()
            in {".ph-repo-auditor.yml", ".ph-repo-auditor.yaml"}
            or path.lower().endswith(
                ("data_dictionary.md", "data-dictionary.md", "codebook.md")
            )
        }
        files: dict[str, str | None] = {path: None for path in file_paths}
        for path in selected:
            response = self._client.get(
                f"/repos/{repository}/contents/{path}",
                params={"ref": ref},
                headers=headers,
            )
            response.raise_for_status()
            encoded = response.json().get("content", "")
            files[path] = base64.b64decode(encoded).decode("utf-8", errors="replace")

        policy_path = next(
            (
                path
                for path in selected
                if path.lower()
                in {".ph-repo-auditor.yml", ".ph-repo-auditor.yaml"}
            ),
            None,
        )
        policy, warnings = parse_policy(
            files.get(policy_path) if policy_path else None
        )
        return audit_repository(repository, files, policy, warnings)

    def publish_check(
        self,
        installation_id: int,
        repository: str,
        head_sha: str,
        report: AuditReport,
    ) -> None:
        token = self.installation_token(installation_id)
        conclusion = "success" if report.passed else "failure"
        response = self._client.post(
            f"/repos/{repository}/check-runs",
            headers=self._installation_headers(token),
            json={
                "name": "Public Health Repository Quality",
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": conclusion,
                "output": {
                    "title": f"Quality score: {report.score}/100 ({report.grade})",
                    "summary": report.to_markdown(),
                },
            },
        )
        response.raise_for_status()
