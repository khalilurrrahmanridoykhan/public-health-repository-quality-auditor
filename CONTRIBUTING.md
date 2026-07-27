# Contributing

Contributions to checks, documentation, tests, and GitHub App behavior are welcome.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

Keep checks transparent and actionable. A check must explain what evidence it uses, why the signal matters, and how a maintainer can improve. Avoid rules that claim to determine scientific validity or rank researchers.

Never add real patient data, GitHub App private keys, webhook secrets, or installation tokens to tests or examples.
