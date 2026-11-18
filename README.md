# ABC Harness

ABC Harness is a local CLI that turns a researcher's question into a
reproducible blockchain simulation. The researcher describes an experiment,
reviews the agent's plan, and approves it. The harness runs SimBlock or
BlockSim in a Docker container and returns a report linked to the raw output.

The project is at its first milestone and cannot run an experiment yet.
[docs/status.md](docs/status.md) says what works today.

## Develop

```bash
uv sync
make check
```

## Docs

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | rules and definitions for changing the repo |
| [docs/README.md](docs/README.md) | the index of all docs |
