.PHONY: install test build reproduce

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -e ".[dev]"
	npm ci

test:
	$(PYTHON) -m pytest
	npm run test:web

build:
	npm run build:sites

reproduce: install test build

