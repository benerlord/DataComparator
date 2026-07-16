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

### Comparison modes

| Mode | Behavior |
|------|----------|
| `exact` | Byte-exact string comparison |
| `numeric` | Round both sides to `decimal_places`, then compare |
| `string` | Normalize (whitespace/case) then compare |

Global `compare.defaults` apply to all fields; per-field settings override.

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
