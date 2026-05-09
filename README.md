# Relay

A tiny CLI for running explicit AI coding workflows from YAML.

## Core Idea

Coding with LLMs is not one-shot generation.

Real development is:

```text
plan -> implement -> review -> iterate
```

Relay makes those workflows programmable. A run is just:

```text
task + workflow + explicit context + model routing
```

Relay is stateless. The only project file it creates is `.relay.yaml`.

## Install

```bash
pip install relay-ai
```

For local development:

```bash
pip install -e ".[dev]"
```

## Quickstart

```bash
relay init review-existing-diff
relay run "review my current changes before I commit"
```

Relay copies a YAML preset into `.relay.yaml`. Edit it like any other project
file.

## How Relay Works

- **Task**: the instruction passed on the command line.
- **Workflow**: the YAML file that defines ordered steps.
- **Steps**: sequential units of work. Relay runs them in order.
- **Roles**: named responsibilities such as `planner`, `reviewer`, or `writer`.
- **Context**: explicit repo input declared per step.
- **Model routing**: each role can point at a different LiteLLM model.

Each step receives the task, prior step outputs, and its declared context. The
step result stays in memory and is printed to the terminal.

## Example Workflow Config

```yaml
workflow: review-existing-diff

roles:
  reviewer: Review the provided task context as if it were an existing diff.

models:
  reviewer: openai:gpt-5.5

steps:
  - id: review
    role: reviewer
    context:
      - git_diff
```

## Built-In Workflows

- `plan-implement-review`: plan a task, propose an implementation, review it.
- `review-existing-diff`: review the current working tree diff.
- `debug-failing-test`: diagnose a failing test, propose a fix, review it.
- `add-tests`: plan, draft, and review focused test coverage.
- `docs-sync`: update docs from the current diff and README context.
- `custom`: a minimal one-step workflow to edit freely.

List presets:

```bash
relay init --list
```

Initialize another preset:

```bash
relay init docs-sync --force
```

## Examples

The `examples/` directory contains small workflow files you can copy from:

- `examples/review-existing-diff.yaml`
- `examples/add-tests.yaml`
- `examples/docs-sync.yaml`

## Explicit Context

Relay uses explicit context instead of automatic retrieval. That keeps runs easy
to understand: the YAML shows exactly what each step can see.

Supported context sources:

- `git_diff`: runs `git diff --no-ext-diff`.
- `file:<path>`: reads one UTF-8 file relative to the project root.
- `glob:<pattern>`: reads matching UTF-8 files relative to the project root,
  with a small content cap.

Example:

```yaml
steps:
  - id: review-docs
    role: reviewer
    context:
      - git_diff
      - file:README.md
      - glob:docs/**/*.md
```

Missing files, empty diffs, non-git directories, and unreadable files appear as
clear placeholder notes in the prompt.

## Prompt Previewing

Use `--show-prompt` to see exactly what Relay would send to each model:

```bash
relay run "review my current changes before I commit" --show-prompt
```

Relay does not call models in prompt preview mode. For later steps, it uses a
clear placeholder where real previous step output would appear.

## Mock Mode

Relay works without API keys by returning deterministic mock responses.

Use the models configured in `.relay.yaml`:

```bash
RELAY_LIVE=1 relay run "review my current changes"
```

Override every configured model with one LiteLLM model:

```bash
RELAY_MODEL=openai:gpt-5.5 relay run "review my current changes"
```

## Philosophy

Relay should feel like:

- `git`
- `pytest`
- `rg`
- `cargo`

It should not feel like:

- an agent framework
- an autonomous coding platform
- an AI operating system

Relay intentionally avoids persistence, replay systems, caches, plugins, DAGs,
async runtimes, vector search, automatic retrieval, memory systems, and agent
abstractions.

## Architecture

```text
relay/
  cli.py
  config.py
  context.py
  executor.py
  llm.py
  prompts.py
  workflow.py
```
