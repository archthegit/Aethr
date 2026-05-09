# Aethr

A tiny CLI for running explicit AI coding workflows from YAML.

## Core Idea

Coding with LLMs is not one-shot generation.

Real development is:

```text
plan -> implement -> review -> iterate
```

Aethr makes those workflows programmable. A run is just:

```text
task + workflow + explicit context + model routing
```

Aethr is stateless. The only project file it creates is `.aethr.yaml`.

## Install

```bash
pip install aethr
```

For local development:

```bash
pip install -e ".[dev]"
```

## Quickstart

```bash
aethr init review-existing-diff
aethr run "review my current changes before I commit"
```

Aethr copies a YAML preset into `.aethr.yaml`. Edit it like any other project
file.

## How Aethr Works

- **Task**: the instruction passed on the command line.
- **Workflow**: the YAML file that defines ordered steps.
- **Steps**: sequential units of work. Aethr runs them in order.
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
aethr init --list
```

Initialize another preset:

```bash
aethr init docs-sync --force
```

## Examples

The `examples/` directory contains small workflow files you can copy from:

- `examples/review-existing-diff.yaml`
- `examples/add-tests.yaml`
- `examples/docs-sync.yaml`

## Explicit Context

Aethr uses explicit context instead of automatic retrieval. That keeps runs easy
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

Use `--show-prompt` to see exactly what Aethr would send to each model:

```bash
aethr run "review my current changes before I commit" --show-prompt
```

Aethr does not call models in prompt preview mode. For later steps, it uses a
clear placeholder where real previous step output would appear.

## Mock Mode

Aethr works without API keys by returning deterministic mock responses.

Use the models configured in `.aethr.yaml`:

```bash
AETHR_LIVE=1 aethr run "review my current changes"
```

Override every configured model with one LiteLLM model:

```bash
AETHR_MODEL=openai:gpt-5.5 aethr run "review my current changes"
```

## Philosophy

Aethr should feel like:

- `git`
- `pytest`
- `rg`
- `cargo`

It should not feel like:

- an agent framework
- an autonomous coding platform
- an AI operating system

Aethr intentionally avoids persistence, replay systems, caches, plugins, DAGs,
async runtimes, vector search, automatic retrieval, memory systems, and agent
abstractions.

## Architecture

```text
aethr/
  cli.py
  config.py
  context.py
  executor.py
  llm.py
  prompts.py
  workflow.py
```
