FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

USER 10001
EXPOSE 8000

CMD ["uvicorn", "ph_repo_auditor.webhook:app", "--host", "0.0.0.0", "--port", "8000"]
