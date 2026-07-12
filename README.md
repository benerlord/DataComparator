# DataComparator

A CLI tool to compare data across Excel files, GaussDB databases, and HTTP APIs.

## Install

```bash
pip install -e .
```

## Quick start

Generate a task template:
```bash
datacompare init excel-vs-gaussdb > task.yaml
```

Edit `task.yaml` and `~/.datacompare/connections.yaml`, then run:
```bash
datacompare run task.yaml --param month=2026-07
```

## Commands

- `datacompare run <task.yaml>` — execute a comparison task
- `datacompare validate <task.yaml>` — validate config and connectivity
- `datacompare init <template>` — emit a template YAML
- `datacompare version` — show version

See `docs/user-guide.md` for full documentation.
