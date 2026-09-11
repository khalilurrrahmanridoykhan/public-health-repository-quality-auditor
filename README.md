# Public Health Repository Quality Auditor

<p align="center">
  <img src="assets/app-logo.png" width="220" alt="Public Health Repository Quality Auditor logo">
</p>

[![CI](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/actions/workflows/ci.yml/badge.svg)](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

A GitHub App and local CLI that reviews public-health research repositories for practical reproducibility, documentation, data governance, and software-quality signals.

[**View the registered GitHub App →**](https://github.com/apps/public-health-repo-auditor)

![Production homepage](assets/production-homepage.png)

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
It also audits non-draft pull requests when they are opened, reopened, marked
ready for review, or updated with new commits.

The production webhook is implemented as a Next.js API route and deployed on
[Cloudflare Workers](https://public-health-repo-auditor.khalilur-ridoy.workers.dev).
The Python FastAPI service and CLI remain available for local or self-hosted use.

> [!IMPORTANT]
> This tool does not certify scientific validity, regulatory compliance, privacy compliance, or research ethics. It helps maintainers identify missing repository-quality signals.

## Try the local CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ph-repo-audit /path/to/research-repository
ph-repo-audit /path/to/research-repository --format json
ph-repo-audit /path/to/research-repository --format sarif
ph-repo-audit /path/to/research-repository --sarif findings.sarif   # write SARIF, still print markdown
ph-repo-audit /path/to/research-repository --pack hygiene           # repeatable; default: every detected pack
```

## Architecture: packs

Checks are grouped into **packs**. Each repository is audited by whichever
packs detect themselves on it — `hygiene` (the 10 checks above) always
applies, `fhir` activates on FHIR Implementation Guide / package
repositories, and `dhis2` activates on DHIS2 App Platform apps and metadata
export bundles (see below for both). More platform packs (OpenMRS, ...) are
planned. Every pack emits `Finding`s (severity, category, file, line, rule ID, fix,
docs link) in addition to `hygiene`'s point-scored `CheckResult`s, so output
is available as Markdown, JSON, and [SARIF 2.1.0](https://sarifweb.azurewebsites.net/)
for GitHub code scanning.

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

The app is registered as [Public Health Repo Auditor](https://github.com/apps/public-health-repo-auditor) with App ID `4402855`.

To finish activating it:

1. Deploy this service to a public HTTPS endpoint.
2. Set the app's webhook URL to the deployed `/webhooks/github` endpoint.
3. Set a strong webhook secret and store the same value in `GITHUB_WEBHOOK_SECRET`.
4. Confirm these repository permissions:
   - **Contents:** Read-only
   - **Checks:** Read and write
   - **Metadata:** Read-only
5. Subscribe to the **Push** event.
6. Generate a private key and configure it as `GITHUB_PRIVATE_KEY`.
7. Install the app on selected research repositories.

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

## Repository policy

Add `.ph-repo-auditor.yml` at the repository root to customize enforcement:

```yaml
minimum_score: 90

disabled_checks:
  - ethics

required_files:
  - CITATION.cff
  - docs/data_dictionary.md

ignore_paths:
  - vendor
  - generated

privacy_terms:
  - privacy
  - de-identified
  - aggregate health data
```

- `minimum_score` accepts an integer from 0 to 100.
- `disabled_checks` accepts `readme`, `license`, `citation`, `dependencies`,
  `reproduction`, `tests`, `data_dictionary`, `provenance`, `privacy`, and
  `ethics`.
- `disabled_packs` accepts `hygiene`, `fhir`, and `dhis2` — turns an entire
  pack off regardless of whether it would otherwise detect itself on the
  repository.
- `required_files` contains exact repository-relative paths.
- `ignore_paths` contains repository-relative path prefixes.
- `privacy_terms` adds repository-specific phrases that satisfy the privacy
  documentation check.

Invalid policy values are reported in the Check Run and do not silently weaken
the default policy.

## FHIR pack

Detected automatically when the repository has a `sushi-config.yaml`/`.yml`,
any `.fsh` file, or a conformance-named JSON file (e.g.
`StructureDefinition-*.json`). Runs entirely offline — no HL7 validator JAR,
no SUSHI invocation, no ValueSet expansion — so it's fast but deliberately
narrower than a full FHIR validator. It inspects `sushi-config.yaml` and any
JSON FHIR resource under an `examples/`, `fsh-generated/`, `fhir/`,
`resources/`, or `tests/` directory (or matching a conformance filename).

| Rule | Severity | What it catches |
| :--- | :--- | :--- |
| `fhir/missing-profile-meta` | warning | An example instance has no `meta.profile`, so conformance can't be checked. |
| `fhir/unresolved-canonical` | error | A profile/ValueSet/binding references a canonical under the IG's own root that no resource in the repo defines. |
| `fhir/unpinned-dependency` | warning | A `sushi-config.yaml` dependency has no exact version (`current`, a range, or missing). |
| `fhir/invalid-fhir-version` | error | `fhirVersion` isn't a released FHIR version or recognised alias (R4, R4B, R5). |
| `fhir/version-mismatch` | error | An `ImplementationGuide` resource's `fhirVersion` disagrees with `sushi-config.yaml`. |
| `fhir/slicing-no-discriminator` | warning | A `StructureDefinition` slices an element with no `slicing.discriminator`. |
| `fhir/pii-in-example` | error | A `Patient`/`RelatedPerson`/`Person` example has a realistic-looking identifier (not an obviously-fake placeholder) and no test-data marker. |
| `fhir/invalid-json` | error | A FHIR-relevant `.json` file doesn't parse. |
| `fhir/fsh-compile-skipped` | info | `.fsh` files exist but SUSHI isn't on `PATH`, so they weren't compiled to check for errors. |

**Deferred to a later pass** (each needs a tool this pack doesn't assume is
available): `$validate`-based conformance checking (HL7 validator JAR),
actually invoking SUSHI to compile `.fsh` (needs filesystem access the `Pack`
interface doesn't carry yet), ValueSet-membership / binding-strength checks
(needs terminology), cardinality-vs-base and FHIRPath-invariant checks (needs
a snapshot or a FHIRPath engine).

An error-severity finding from **any** pack fails the audit
(`report.passed`), even if the hygiene score alone clears the threshold.

#### FHIR: missing profile meta

Add `meta.profile` with the canonical URL(s) this example conforms to.

#### FHIR: unresolved canonical

Create the missing profile/ValueSet/CodeSystem, or fix the typo in the
canonical URL.

#### FHIR: unpinned dependency

Pin the dependency to an exact released version instead of `current`, a
range, or a branch name.

#### FHIR: invalid fhir version

Declare a released FHIR version (e.g. `4.0.1`) or a recognised alias (`R4`,
`R4B`, `R5`).

#### FHIR: version mismatch

Make the `ImplementationGuide` resource's `fhirVersion` match
`sushi-config.yaml` — usually means rebuilding it with SUSHI.

#### FHIR: slicing no discriminator

Add `slicing.discriminator` (a type and path) to the sliced element, or
remove the slicing if it isn't needed.

#### FHIR: pii in example

Use an obviously-fake identifier (a repeating or sequential digit pattern),
or tag the resource `meta.tag =
http://terminology.hl7.org/CodeSystem/v3-ActReason#HTEST`.

#### FHIR: invalid json

Fix the JSON syntax error, or run the file through SUSHI or a JSON linter.

#### FHIR: fsh compile skipped

Install SUSHI (`npm i -g fsh-sushi`) so `.fsh` files get compiled and
checked. This is an informational finding, not a failure.

## DHIS2 pack

Detected automatically when the repository has `d2.config.js`/`.json`, a
`package.json` depending on any `@dhis2/*` package, or a JSON file with a
DHIS2-distinctive metadata collection key (`organisationUnits`,
`categoryCombos`, `programRules`, `sqlViews`, ...). Source-level checks are
regex heuristics over JS/TS/JSX/TSX text — deliberately conservative (a
literal quoted string, not an arbitrary JS parse) to keep false positives
low.

| Rule | Severity | What it catches |
| :--- | :--- | :--- |
| `dhis2/invalid-d2-config` | error | `d2.config` has no recognised `type` (`app`, `widget`, `app+widget`) or no `entryPoints`. |
| `dhis2/hardcoded-instance-url` | warning | A literal `play.dhis2.org`/`*.dhis2.org`/`*.dhis2.com` URL in source instead of the app-runtime config or a Route. |
| `dhis2/raw-fetch-to-api` | warning | `fetch(`/`axios.*(` called with a literal `/api/...` string instead of `useDataQuery`/`useDataMutation`. |
| `dhis2/metadata-duplicate-uid` | error | The same `id` defined more than once in a metadata export. |
| `dhis2/metadata-dangling-ref` | error | A reference field (`categoryCombo`, `dataElement`, `program`, ...) points at an id missing from the bundle's own matching collection — only checked when that collection is actually present, so an intentionally-partial export isn't flagged. |
| `dhis2/sqlview-mutating-statement` | error | A SQL View's `sqlQuery` contains `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`CREATE`/`GRANT`/`REVOKE` instead of a read-only `SELECT`. |
| `dhis2/program-rule-undefined-var` | warning | A program rule condition/action references `#{variable}` not in `programRuleVariables`, or `V{builtin}` that isn't a documented DHIS2 built-in variable. |

**Dropped after testing against 4 real DHIS2 App Platform apps:**
`no-app-runtime-provider` (from the original design) would have flagged
every one of them — `@dhis2/cli-app-scripts` wraps the app in a `<Provider>`
at build time, so modern App Platform apps never author their own.

**Deferred to a later pass:** `missing-translations` (no reliable way to
know which locales an app must support), `version-compat` (would need a
maintained API-parameter → minimum-DHIS2-version table), `no-i18n-extraction`
(a naive regex over JSX text is too noisy without a real JSX parser).

#### DHIS2: invalid d2 config

Set `type` to one of the App Platform's supported types and add an
`entryPoints` object, e.g. `{ app: './src/App.js' }`.

#### DHIS2: hardcoded instance url

Read the instance base URL from `useConfig()`/`useDataEngine()`, or define a
Route instead of a literal URL.

#### DHIS2: raw fetch to api

Use `useDataQuery`/`useDataMutation` (or `useDataEngine`) so auth, the
instance base URL, and error handling are handled for you.

#### DHIS2: metadata duplicate uid

DHIS2 UIDs must be globally unique; regenerate one of the duplicates.

#### DHIS2: metadata dangling ref

Include the referenced object in the export, or confirm it already exists
on the target instance before importing.

#### DHIS2: sqlview mutating statement

SQL Views must be read-only `SELECT` queries; DHIS2 will reject or refuse to
run one that mutates data.

#### DHIS2: program rule undefined var

Add a matching `programRuleVariable`, or check for a typo against DHIS2's
documented `V{...}` built-in variables.

## Audit guidance

### Project documentation

Add a root README that explains the public-health question, methods, data,
expected outputs, limitations, and exact usage steps.

### License

Add a software license and state separately whether included datasets have
different access or reuse conditions.

### Citation

Add `CITATION.cff` or `codemeta.json` with authors, title, version, and the
preferred citation.

### Dependencies

Commit a supported dependency specification such as `requirements.txt`,
`pyproject.toml`, `environment.yml`, `renv.lock`, or `package-lock.json`.

### Reproduction

Provide a Makefile or workflow with one documented command that regenerates
the reported outputs.

### Tests and CI

Add automated tests and CI for data validation, transformations, and important
analytical invariants.

### Data dictionary

Document every variable, type, unit, missing-value convention, and allowed
value or category.

### Data provenance

Record each data source, access date, license, geographic and temporal scope,
and transformation.

### Privacy

State whether data are aggregate, synthetic, de-identified, person-level, or
sensitive. Explain access controls and safe-use limits where applicable.

### Ethics

State the ethics or IRB basis, consent status, approval identifier when
appropriate, or why review was not required.

## Hosted service

- [Onboarding and manual-audit dashboard](https://public-health-repo-auditor.khalilur-ridoy.workers.dev/dashboard)
- [Privacy policy](https://public-health-repo-auditor.khalilur-ridoy.workers.dev/privacy)
- [Terms of service](https://public-health-repo-auditor.khalilur-ridoy.workers.dev/terms)
- [Support](https://public-health-repo-auditor.khalilur-ridoy.workers.dev/support)

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

To install dependencies, run every test, and build the production worker with
one command:

```bash
make reproduce
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Support

For installation help, bug reports, or responsible-use questions, open a
[GitHub issue](https://github.com/khalilurrrahmanridoykhan/public-health-repository-quality-auditor/issues)
or email [khalilurrahmanridoykhan@gmail.com](mailto:khalilurrahmanridoykhan@gmail.com).
