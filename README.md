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

For reviewing the current repo:

```bash
aethr init review-existing-diff
aethr run "review my current changes before I commit"
```

If you omit the task entirely, `aethr run` opens your editor first and then
drops into the interactive session after the first step:

```bash
aethr run
```

For a multi-model implementation workflow:

```bash
aethr init plan-implement-review --force
aethr run "add support for loading .env files"
```

Aethr copies a YAML preset into `.aethr.yaml`. Edit it like any other project
file. The default `plan-implement-review` preset uses OpenCode for the
implementation step, so install the `opencode` CLI if you want that step to
edit the working tree.
In that preset, the reviewer reads `latest_diff`, meaning the most recent
implementation diff rather than the whole repository diff.

## How Aethr Works

- **Task**: the instruction passed on the command line.
- **Workflow**: the YAML file that defines ordered steps.
- **Steps**: sequential units of work. Aethr runs them in order.
- **Roles**: named responsibilities such as `planner`, `reviewer`, or `writer`.
- **Context**: explicit repo input declared per step.
- **Artifacts**: structured implementation output such as changed files and
  diffs, passed forward in memory to later steps.
- **Model routing**: each role can point at a different LiteLLM model.

Each step receives the task, prior step outputs, and its declared context. The
step result stays in memory, streams to the terminal as it is generated, and
is printed in a Rich panel when complete.

## Example Workflow Config

```yaml
workflow: review-existing-diff

roles:
  reviewer: Review the provided task context as if it were an existing diff.

models:
  reviewer: openai:gpt-4o-mini

steps:
  - id: review
    role: reviewer
    context:
      - git_diff
```

For real code changes, Aethr can hand an implementation step to OpenCode:

```yaml
  - id: implement
    role: implementer
    backend: opencode
    unsafe_permissions: true
```

That keeps the workflow explicit while letting a real coding agent edit the
working tree. Leave `unsafe_permissions` off if you want OpenCode to keep its
normal permission checks.

## Built-In Workflows

- `plan-implement-review`: plan a task, then hand implementation to OpenCode
  before reviewing the resulting `latest_diff`.
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

These examples intentionally show different providers across roles so you can
see routing in practice, not just the default presets.

## Explicit Context

Aethr uses explicit context instead of automatic retrieval. That keeps runs easy
to understand: the YAML shows exactly what each step can see.

Supported context sources:

- `git_diff`: runs `git diff --no-ext-diff`.
- `latest_diff`: the most recent implementation diff from the prior step.
- `file:<path>`: reads one UTF-8 file relative to the project root.
- `glob:<pattern>`: reads matching UTF-8 files relative to the project root,
  with a small content cap.

Use `git_diff` when a step should inspect the whole working tree. Use
`latest_diff` when a later step should inspect only the most recent
implementation output from the workflow itself.

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

## Loops

A step can repeat an earlier contiguous slice of the workflow until a condition
is met. This stays explicit in YAML and keeps the workflow sequential.

Example:

```yaml
steps:
  - id: implement
    role: implementer
    backend: opencode

  - id: review
    role: reviewer
    repeat:
      back_to: implement
      until_review_pass: true
      max_iterations: 3
```

Use this for bounded review/fix cycles. The controller step should emit
`Review status: pass` when there are no high or medium findings, and
`Review status: revise` when another pass is needed.

For loop-heavy workflows, you can also narrow step history visibility:

```yaml
steps:
  - id: implement
    role: implementer
    backend: opencode
    history_visibility: latest
```

Use `latest` when the next step only needs the most recent result, `summary`
when you want a compressed history, and `none` when the step should only see
its explicit context.

## Prompt Previewing

Use `--show-prompt` to see exactly what Aethr would send to each model:

```bash
aethr run "review my current changes before I commit" --show-prompt
```

Aethr does not call models in prompt preview mode. For later steps, it uses a
clear placeholder where real previous step output would appear.

## Mock Mode

Aethr works without API keys by returning deterministic mock responses.

Aethr also loads a project-level `.env` automatically before model calls, so
credentials can live alongside the workflow file without extra flags.

You can start from the included template:

```bash
cp .env.example .env
```

Use the models configured in `.aethr.yaml`:

```bash
AETHR_LIVE=1 aethr run "review my current changes"
```

Override every configured model with one LiteLLM model:

```bash
AETHR_MODEL=openai:gpt-4o-mini aethr run "review my current changes"
```

## Auth

Use `aethr auth login` to write a provider key into the project `.env` file.
Aethr loads that file automatically on the next run.

```bash
aethr auth login openai
aethr auth status
```

Supported providers in the helper are:

- `openai`
- `anthropic`
- `google` / `gemini`
- `openrouter`
- `xai`

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

If a workflow fails, Aethr writes a temporary checkpoint file and prints a
compact resume command. Pass that checkpoint back with `--resume-checkpoint`
to continue from the next step without rerunning the earlier ones. Use
`--verbose` if you want the raw checkpoint JSON.

## Future Work

One likely future UX is workflow promotion: take a one-off run that worked and
turn it into an editable `.aethr.yaml` workflow. The idea is to help users go
from ad hoc sessions to repeatable workflows without introducing session
storage, replay systems, or hidden history.

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
