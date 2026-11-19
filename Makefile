# One target per command in AGENTS.md. Each target is the command you would
# otherwise type.

.PHONY: check lint fmt test test-docker test-live image example example-blocksim

check: lint test          ## run before every commit

lint:                     ## lint src/ and tests/
	uv run ruff check src tests

fmt:                      ## format and auto-fix
	uv run ruff format src tests
	uv run ruff check --fix src tests

test:                     ## offline tests: no Docker, no API key
	uv run pytest -m "not docker and not live"

test-docker:              ## tests that need a Docker daemon
	uv run pytest -m docker

test-live:                ## tests that call a real model or API
	uv run pytest -m live

image:                    ## build the execution images of all simulators
	uv run abc-harness image build

example:                  ## review and run the M1 example plan
	uv run abc-harness run examples/simblock-baseline.toml

example-blocksim:         ## review and run the BlockSim example plan
	uv run abc-harness run examples/blocksim-baseline.toml
