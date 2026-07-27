# Public Health Repository Quality Auditor

[![CI](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

A GitHub App and local CLI that reviews public-health research repositories for practical reproducibility, documentation, data governance, and software-quality signals.

It checks for:

- Project documentation and data provenance
- Code and data licensing
- Machine-readable citation metadata
- Dependency and environment specifications
- One-command reproduction
- Automated tests or CI
- Data dictionaries or codebooks
- Privacy and sensitive-data warnings
- Ethics or IRB statements

The auditor produces a score, grade, evidence table, and actionable recommendations as a GitHub Check Run on every push.

> [!IMPORTANT]
> This tool does not certify scientific validity, regulatory compliance, privacy compliance, or research ethics. It helps maintainers identify missing repository-quality signals.

## Try the local CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ph-repo-audit /path/to/research-repository
ph-repo-audit /path/to/research-repository --json
```

## Run the webhook service

Copy `.env.example` values into your deployment environment:

```bash
export GITHUB_APP_ID="123456"
export GITHUB_WEBHOOK_SECRET="replace-with-a-random-secret"
export GITHUB_PRIVATE_KEY="$(cat private-key.pem)"
uvicorn ph_repo_auditor.webhook:app --host 0.0.0.0 --port 8000
```

Health check: `GET /health`  
GitHub webhook endpoint: `POST /webhooks/github`

## Register the GitHub App

1. Open **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Name the app `Public Health Repository Quality Auditor`.
3. Set the homepage to this repository.
4. Set the webhook URL to your deployed `/webhooks/github` endpoint.
5. Generate a strong webhook secret and store the same value in `GITHUB_WEBHOOK_SECRET`.
6. Grant repository permissions:
   - **Contents:** Read-only
   - **Checks:** Read and write
   - **Metadata:** Read-only
7. Subscribe to the **Push** event.
8. Create the app, generate a private key, and configure `GITHUB_APP_ID` and `GITHUB_PRIVATE_KEY`.
9. Install the app on selected research repositories.

Use a secrets manager in production. Never commit the private key or webhook secret.

## Architecture

```text
GitHub push webhook
        │
        ▼
HMAC signature verification
        │
        ▼
GitHub App installation token
        │
        ▼
Repository tree + selected documentation
        │
        ▼
Rule-based quality audit
        │
        ▼
GitHub Check Run with score and recommendations
```

## Scoring

The initial rule set uses transparent, deterministic checks totaling 100 points. The score is designed for maintainers and should not be used to rank researchers or institutions. Future versions can support configurable policies for epidemiology, surveillance, modelling, and health-information-system projects.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Support

For installation help, bug reports, or responsible-use questions, open a
[GitHub issue](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/issues)
or email [khalilurrahmanridoykhan@gmail.com](mailto:khalilurrahmanridoykhan@gmail.com).
