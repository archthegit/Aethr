# Relay

Relay is a lightweight CLI for configurable AI coding workflows.

It is meant to feel like Unix pipes for coding agents: small commands,
explicit configuration, sequential execution, and no runtime state to manage.

## Install

```bash
pip install -e .
```

## Initialize A Workflow

List built-in presets:

```bash
relay init --list
```

Initialize interactively:

```bash
relay init
```

Initialize a specific preset:

```bash
relay init plan-implement-review
```

This writes the only project file Relay needs:

```text
.relay.yaml
```

Presets are plain YAML templates. Users can inspect, edit, and commit them.

## Run

```bash
relay run "add a JSON export command"
```

Relay runs the configured steps in memory and prints each result to the
terminal. It does not create run directories, state files, caches, history, or
artifact stores.

By default, Relay returns deterministic mock model responses so workflows run
without credentials. To use the models from `.relay.yaml`, set:

```bash
RELAY_LIVE=1 relay run "add a JSON export command"
```

To override every role with one LiteLLM model:

```bash
RELAY_MODEL=openai:gpt-5.5 relay run "add a JSON export command"
```

## Workflow Format

```yaml
workflow: plan-implement-review

roles:
  planner: Create a concise implementation plan with ordered steps and risks.
  implementer: Produce the proposed code change or patch content from the plan.
  reviewer: Review the prior output for bugs, gaps, and missing tests.

models:
  planner: openai:gpt-5.5
  implementer: anthropic:claude-sonnet
  reviewer: openai:gpt-5.5

steps:
  - id: plan
    role: planner

  - id: implement
    role: implementer

  - id: review
    role: reviewer

review_loop:
  enabled: true
  max_iterations: 3
```

When `review_loop.enabled` is true, Relay repeats only the final configured
step. `max_iterations: 3` means the final step runs once during the normal
workflow, then two more times with prior step results in memory as context. It
does not rerun the full workflow.

## Architecture

```text
relay/
  cli.py        Typer CLI entrypoint
  config.py     Pydantic workflow schema and YAML loader
  workflow.py   built-in YAML template discovery and initialization
  executor.py   tiny in-memory sequential runner
  llm.py        tiny LiteLLM wrapper with mock fallback
  prompts.py    prompt builder

relay/workflows/
  plan_implement_review.yaml
  review_existing_diff.yaml
  test_failure_debug.yaml
  docs_update.yaml
  custom.yaml
```

## Philosophy

Relay is workflow orchestration, model routing, and review loops. It is not run
management, artifact persistence, observability infrastructure, or a stateful
agent environment.

The project intentionally avoids plugins, DAG engines, async runtimes, agent
swarms, vector databases, long-term memory, GUIs, web servers, replay systems,
and artifact explorers.
