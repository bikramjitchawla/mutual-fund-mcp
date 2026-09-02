.PHONY: install install-claude run run-http test docker

install:
	uv sync --extra dev

install-claude:
	uv run fastmcp install claude-desktop mutual_fund_mcp/server.py:mcp --name mutual-fund-mcp --with-editable . --env MF_PROVIDER=mfapi

run:
	uv run mutual-fund-mcp

run-http:
	uv run mutual-fund-mcp --transport http --host 127.0.0.1 --port 8000

test:
	uv run pytest -q

docker:
	docker compose up --build

