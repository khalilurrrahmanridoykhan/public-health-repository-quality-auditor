# Data Dictionary

The auditor processes repository metadata and GitHub webhook payloads. It does
not require patient-level or other sensitive research data. Repository file
contents are inspected only when needed to identify documented quality signals.

## GitHub push payload

| Field | Type | Required | Allowed values or format | Meaning |
|---|---|---:|---|---|
| `installation.id` | Integer | Yes | Positive GitHub installation ID | Identifies the GitHub App installation used to request a short-lived token. |
| `repository.full_name` | String | Yes | `owner/repository` | Identifies the repository being audited. |
| `after` | String | Yes | 40-character Git commit SHA | Identifies the commit evaluated by the audit. |
| `deleted` | Boolean | No | `true` or `false`; missing means `false` | Prevents auditing a deleted Git reference. |
| `X-GitHub-Event` | Header string | Yes | `ping` or `push`; other events are ignored | Selects the webhook-processing path. |
| `X-Hub-Signature-256` | Header string | Yes | `sha256=` followed by a hexadecimal HMAC | Authenticates the payload before processing. |

## Repository file map

| Field | Type | Required | Missing-value convention | Meaning |
|---|---|---:|---|---|
| Repository name | String | Yes | Not allowed | Repository identifier displayed in the report. |
| File path | String | Yes | Not allowed | Repository-relative path used to detect evidence files. |
| File content | String or null | No | `null` means content was not downloaded | Text used for README-based provenance, privacy, and ethics checks. |

Paths are normalized to lowercase and stripped of leading or trailing `/`
characters. Scores are integer points from deterministic checks and total
between 0 and 100. Grades are derived from that total; missing evidence receives
zero points for the corresponding check.

## Privacy and retention

The production service evaluates webhook data in memory and does not implement a
repository-content database. GitHub delivery metadata may remain available in
GitHub's webhook delivery history. Never commit private keys, webhook secrets,
access tokens, patient data, or directly identifying research data.

