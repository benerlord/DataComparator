# DataComparator User Guide

## Sources

- **Excel** (`.xlsx`, `.xls`): multi-sheet selection, configurable header row, force-string reading
- **GaussDB A** (DWS / openGauss / GaussDB 100 PG-compat mode): PostgreSQL-protocol compatible via psycopg2; user provides full SELECT query. Default when `variant` is omitted.
- **GaussDB T** (OLTP, `variant: t`): JDBC via JayDeBeApi + gsjdbc4.jar. Requires `pip install 'datacompare[gaussdb-t]'` and JRE 8+. See README for connection example.
- **HTTP API**: three auth strategies (none / bearer / cookie); three pagination modes (page / offset / cursor); JSONPath extraction

## Configuration

Two YAML files:
- **Task**: `task.yaml` — describes sources, match keys, compare rules, output
- **Connections**: `~/.datacompare/connections.yaml` — connection details and credentials (never commit)

### Parameter substitution

Three placeholder types:
- `${ENV_VAR}` — environment variable
- `{{param.NAME}}` — CLI `--param NAME=VALUE`
- `{{today}}` / `{{now}}` — built-in

### Key regex normalization (v0.3+)

When left and right keys differ in surface form but map to the same logical
value via a regex (e.g. left `"ORD-2026-000123"` vs right `"123"`), attach
`left_regex` / `right_regex` to the key entry:

```yaml
match:
  keys:
    - left: order_no
      right: order_id
      left_regex: 'ORD-\d{4}-0*(\d+)'   # extracts "123"
```

Rules:
- Uses Python `re.fullmatch`; the whole string must match
- 0 or 1 capture group; with a capture group `group(1)` wins, otherwise `group(0)`
- 2 or more capture groups fail at `datacompare validate` time (use non-capturing
  groups `(?:...)` for grouping)
- Any row that fails to match aborts the run with exit code 2 and emits a
  `key_regex_mismatch` log event
- `None` values pass through unchanged (not fed to the regex)

For case-insensitive or multiline matching use inline flags: `(?i)ord-\d+`.

### Key alias for canonical name conflicts (v0.6+)

Give a key a custom canonical column name via `alias` when `k.right` would
collide with a field's canonical:

```yaml
match:
  keys:
    - left: id
      right: name
      right_regex: '.*@@(.*)'
      alias: join_id     # key canonical becomes "join_id" instead of "name"
```

Rules:
- `alias` is optional; when unset, canonical = `k.right` (unchanged behavior)
- Any non-empty string is valid
- If `key_canonical_name(k) == field_canonical_name(f)` for any pair in
  the same task, loader raises `ConfigError` — add `alias` to disambiguate

### Field regex normalization (v0.6+)

Mirror of `KeyMapping.left_regex/right_regex` for compare fields:

```yaml
compare:
  fields:
    - left: name
      right: name
      right_regex: '(.*)@@.*'
```

Rules:
- Uses Python `re.fullmatch`; the whole string must match
- 0 or 1 capture group; with a capture group `group(1)` wins, otherwise
  `group(0)`
- 2 or more capture groups fail at `datacompare validate` time (use
  non-capturing groups `(?:...)`)
- `None` values pass through unchanged
- **Failure semantics** (differs from key regex): row that fails to match
  → value becomes `RegexError` sentinel, gets classified as
  `regex_error` diff type in the report; other rows keep comparing.
  This is deliberate: bad key kills the join, bad field is just a data
  quality issue.

### Source column duplication (v0.6+)

If the same source column is referenced by both a key and a field
(e.g. right's `name` is used as join key via alias AND as compare field),
`apply_column_mapping` produces two canonical columns from that one source.
This is what makes the combination "key regex + field regex" on the same
column work — the source column is copied per canonical before regexes
apply, so each canonical column gets its own regex without interfering.

### Batch mode (v0.4+): one YAML runs N comparisons

When one Excel has dozens of sheets with different schemas, or you need to run
several independent comparisons in a batch, use batch mode:

```yaml
name: cmdb_multi_sync
on_error: continue        # continue (default) | fail_fast

sources:                  # defaults, deep-merged into each sub-task
  left: {type: excel, path: manage.xlsx}
  right: {type: gaussdb, connection: prod_cmdb}

output:
  dir: ./reports          # each sub-task auto-lands in ./reports/{sub_task.name}/
  formats: [html, json]

tasks:
  - name: physical_host
    sources:
      left: {sheets: [{name: "PHYSICAL_HOST"}]}
      right: {query: "SELECT ... FROM physical_host"}
    match: {keys: [{left: id, right: id}]}
    compare: {fields: [...]}

  - name: cloud_vm
    sources:
      left: {sheets: [{name: "CLOUD_VM"}]}
      right: {query: "SELECT ... FROM cloud_vm"}
    match: {keys: [{left: id, right: id}]}
    compare: {fields: [...]}
```

Rules:
- Presence of `tasks:` at the top level triggers batch mode; without it the
  file is interpreted as a single-task YAML (existing behavior unchanged)
- **Deep merge**: dicts recurse; lists replace wholesale; a nested dict whose
  `type` changes between defaults and sub-task is replaced entirely (avoids
  `gaussdb.connection` leaking when the sub-task switches to `type: api`)
- Each sub-task writes to `{defaults.output.dir}/{sub_task.name}/report.*`
  plus its own `run-{ts}.log`
- Aggregate meta-events land in `{defaults.output.dir}/batch.log` (one
  `batch_start` / `task_start` / `task_end` / `batch_end` JSON line each)
- Exit code priority: `2` (runtime error) > `10` (diff + `--fail-on-diff`)
  > `1` (config error) > `0`

Generate a template with:
```bash
datacompare init batch-example -o batch.yaml
```

### Comparison modes

| Mode | Behavior |
|------|----------|
| `exact` | Byte-exact string comparison |
| `numeric` | Round both sides to `decimal_places`, then compare |
| `string` | Normalize (whitespace/case) then compare |

Global `compare.defaults` apply to all fields; per-field settings override.

### 字面量字段值（v0.5+）

比对字段每侧必须恰好指定 `<side>` 或 `<side>_literal` 之一：

```yaml
compare:
  fields:
    - {left: real_col, right: real_col}          # 常规：两侧都是列名
    - {left_literal: "Azone", right: type}       # 左侧字面量字符串
    - {left_literal: null, right: deleted_at}    # 左侧字面 null
    - {left: name, right_literal: "prod"}        # 右侧字面量
```

规则：
- 每侧的 `<side>` 和 `<side>_literal` **互斥**，`datacompare validate` 时报错
- 字面量走与列值**完全相同**的 normalize 管线：`mode` / `parse_unit` /
  `null_equivalents` / `decimal_places` 等全部生效
- 字面量 `null` 用 YAML `null`（不是空串）
- 不适用于 match keys（`match.keys` 只能是列名——字面量 join key 会造成
  笛卡尔积无意义）
- 常见用途：右侧库表某字段应为固定枚举值 / 应为 null / 应为固定数字

### Unit parsing

For fields like `"30 TB"`, set `parse_unit: true` with `unit_category` (`storage` / `time` / `length` / `mass`) and `normalize_to` (target unit). Comparison then happens in normalized units.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration error |
| 2 | Data source connect/read failure |
| 3 | Internal error |
| 10 | Success but diffs found, and `--fail-on-diff` was set |

## Examples

See `examples/*.yaml` for ready-to-run configurations.
