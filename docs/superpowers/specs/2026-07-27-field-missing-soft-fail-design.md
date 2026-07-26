# 字段缺列软失败设计规范

**日期：** 2026-07-27
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划
**目标版本：** v0.8

## 问题背景

当前（v0.7）行为：`task.compare.fields` 里任何一个字段引用的源列在左侧或右侧不存在
时，`apply_column_mapping`（`src/datacompare/normalize/columns.py:107-114`）立即抛
`ConfigError`，整个 task 直接失败。批次模式下：

- 该 sub-task 状态 `failed`，`comparison_result=None`
- 输出目录里没有 `report.html`/`report.json`
- `batch_summary.json` 只有 error 信息，没有任何比对统计
- 其它字段哪怕都存在也不会被比对

**典型触发场景**：`batch.yaml` 中比对两个 excel 的 `physical_host` task 字段配错
一个字母，日志：
```
[sources.left] columns not found in left source: ['vmemorys']
提示: available columns: ['__sheet__', 'id', 'name', 'reId', 'vmemory', 'hostIp', 'nativeId']
```
结果整个 physical_host 任务无任何比对产出。

**痛点：** 一个字段名的小拼写错误，代价是整个 task 的比对结果全部丢失。用户需要
的是"该字段跳过、其它字段正常比对、缺列本身在报告里可见"的软失败语义。

## 方案概览

把"缺列检测"从 `apply_column_mapping` 内部的一次性 raise 拆开：

- **key 缺列** 仍然硬失败（在 `apply_column_mapping` 内部 raise `ConfigError`）——
  没 key 无法 join，任何软化都没意义
- **field 缺列** 不再抛异常，而是上报给 engine
- **engine** 收到两侧 missing 集合后：
  - 同一 field canonical 在**双侧都缺** → `ConfigError`（几乎肯定是 YAML 字段名
    全拼错，应及时暴露）
  - **单侧缺** → 跳过该字段的 per-row 比对，在 `diff_details` 追加**一条**汇总
    记录，其它字段照常比对
- 新增 `DiffType.FIELD_MISSING = "field_missing"`，HTML 用灰色背景与其它 diff
  类型区分（灰色暗示"结构问题非值问题"）
- **不加 YAML 开关**：直接改默认行为。想严格 fail 的用户可以用 `--fail-on-diff`
  让 exit code 变 10（因为缺列会产生汇总 diff 记录）

## 汇总 diff 记录形状

进 `diff_details` DataFrame 的字典：

```python
{
    <key_col_1>: "",       # 所有 key 列填空串（结构性缺失，非行级）
    <key_col_2>: "",
    "field": "vmemorys",
    "left_value": "字段不存在",
    "right_value": "(右侧 10000 行有值)",  # N = 该侧数据源总行数（right_total）
    "diff_type": "field_missing",
}
```

**字段规则：**

- key 列一律填**空串**（reporter 无需特判，HTML 表格显示为空即可）
- `left_value` / `right_value` 是**中文字面量**，不走 sentinel dataclass 路径（这
  不是行级值错误，无需跟 `CoerceError` / `RegexError` 共享 `_display` 逻辑）
- 存在侧的描述用 `right_total` / `left_total`（数据源总行数），而非 `matched_rows`
  ——因为字段缺失时"能对应几行"无意义，总行数更直观
- 每个缺列的字段产生**一条**汇总记录（无论对面数据源有几行）

## 具体走查：多字段各自单侧缺

配置示例：
```yaml
compare:
  fields:
    - {left: id, right: id}
    - {left: vmemorys, right: vmemorys}   # 左缺（左边真实列名是 vmemory）
    - {left: hostname, right: hostname}   # 右缺
    - {left: name, right: name}           # 两边都有
```

**处理顺序**（按 `task.compare.fields` **声明顺序**遍历）：

| 顺序 | field | 处理 |
|---|---|---|
| 1 | `id` | 正常 per-row 比对 |
| 2 | `vmemorys` | 跳过 per-row，追加一条汇总：`left_value="字段不存在"`, `right_value="(右侧 N 行有值)"`, `diff_type="field_missing"` |
| 3 | `hostname` | 跳过 per-row，追加一条汇总：`left_value="(左侧 M 行有值)"`, `right_value="字段不存在"`, `diff_type="field_missing"` |
| 4 | `name` | 正常 per-row 比对 |

**统计影响**：
- `diff_rows` = `<id/name 的真实 diff 数> + 2`（两条汇总各 +1）
- `matched_rows` / `identical_rows` / `left_only` / `right_only` 均不受影响
- `errors` 列表**不加**（`FieldError` 用于值级 type/unit/regex 错误，字段缺列是
  结构问题不塞这里）

## 边界情况

| 情况 | 行为 |
|---|---|
| 任一 key 在任一侧缺列 | `ConfigError`（`apply_column_mapping` 内部抛，原路径不变） |
| 同一 field canonical 在**双侧都缺** | `ConfigError`（engine 抛，消息：`field 'X' not found in either source; available left=[...] right=[...]`） |
| field canonical 在**单侧缺** | 软失败，汇总 diff 记录 |
| literal 字段（无 source 列那侧本来就没列名要匹配） | 不受影响，走 `literal_fields` 分支 |
| 缺 field 依赖 regex/type/unit/decimal | 全部跳过——字段压根不 normalize |
| duplicate key 检测 | 不受影响 |
| left_only / right_only 计算 | 不受影响 |

**日志事件**（`normalize_side` 或 engine 内 emit，INFO 级别）：
```
event=field_column_missing side=left field=vmemorys
      available_columns=['id','name','reId','vmemory','hostIp','nativeId']
```

## 数据结构与签名变化

### 新增 `NormalizedSide` 数据类

`src/datacompare/normalize/pipeline.py`：

```python
@dataclass(frozen=True)
class NormalizedSide:
    df: pd.DataFrame
    missing_field_canonicals: frozenset[str]
```

纯数据容器，不带方法。`normalize_side` 之后任何消费方都要显式取 `.df`。

### `apply_column_mapping` 签名变更

`src/datacompare/normalize/columns.py`：

```python
# 旧
def apply_column_mapping(df, keys, fields, side) -> pd.DataFrame

# 新
def apply_column_mapping(df, keys, fields, side) -> tuple[pd.DataFrame, frozenset[str]]
```

内部拆分：
- 收集 `key_tasks: list[(src, canonical)]` 和 `field_tasks: list[(src, canonical)]`
- **key 缺列** 立即 raise `ConfigError`（不变）
- **field 缺列** 只从 `field_tasks` 里剔除，把 canonical 加入 `missing_field_canonicals`
- literal 字段走 `literal_fields` 分支，不进 missing 检测
- 复制剩余的 (src, canonical) 到 result df

### `normalize_side` 返回类型

`src/datacompare/normalize/pipeline.py`：

```python
# 旧
def normalize_side(raw, keys, compare, side) -> pd.DataFrame

# 新
def normalize_side(raw, keys, compare, side) -> NormalizedSide
```

管线内 regex/coerce/decimal 步骤天然通过 `if col in df.columns` 跳过缺列，但要显
式 assert 一下没有意外访问缺列。

### `DiffType` 枚举扩展

`src/datacompare/engine/result.py`：

```python
class DiffType(str, Enum):
    VALUE_MISMATCH = "value_mismatch"
    TYPE_ERROR = "type_error"
    UNIT_ERROR = "unit_error"
    REGEX_ERROR = "regex_error"
    NULL_MISMATCH = "null_mismatch"
    FIELD_MISSING = "field_missing"   # 新增
```

## Engine 层实现要点

`src/datacompare/engine/memory.py`（`disk.py` 镜像同样改动）：

1. 消费 `NormalizedSide.df` 而不是裸 df
2. `_check_both_sides_missing(left_missing, right_missing)` helper：
   - 求交集 `left_missing & right_missing`
   - 非空 → raise `ConfigError`，列出所有双侧缺的 field 名
3. per-field 循环里，在进入 per-row 迭代之前判定：
   ```python
   for f in task.compare.fields:
       canonical = field_canonical_name(f)
       if canonical in left_missing:
           diff_records.append(_build_field_missing_record(
               canonical, side_missing="left",
               key_cols=key_cols, other_side_row_count=right_total,
           ))
           continue
       if canonical in right_missing:
           diff_records.append(_build_field_missing_record(
               canonical, side_missing="right",
               key_cols=key_cols, other_side_row_count=left_total,
           ))
           continue
       # 正常 per-row 比对
       ...
   ```
4. 构建 `left_only_rows` / `right_only_rows` 时，对缺列**补齐 schema**：填全 `"字段
   不存在"` 常量列（选 A 方案），reporter 无需判断列存在性

### `_build_field_missing_record` 辅助

放在 `engine/memory.py` 或抽到 `engine/_field_missing.py`：

```python
def _build_field_missing_record(
    field_canonical: str,
    side_missing: Literal["left", "right"],
    key_cols: list[str],
    other_side_row_count: int,
) -> dict:
    """构建一条汇总 diff 记录。key 列填空串。"""
    return {
        **{k: "" for k in key_cols},
        "field": field_canonical,
        "left_value": "字段不存在" if side_missing == "left"
                      else f"(左侧 {other_side_row_count} 行有值)",
        "right_value": "字段不存在" if side_missing == "right"
                       else f"(右侧 {other_side_row_count} 行有值)",
        "diff_type": DiffType.FIELD_MISSING.value,
    }
```

## HTML 呈现

`src/datacompare/reporters/templates/html_report.jinja2` 的 `<style>` 内新增：

```css
tr.field_missing { background: #ececec; }
```

灰色背景语义："这不是值差异，是结构缺失"。跟已有 `value_mismatch=淡黄`、
`null_mismatch=橙`、`type_error/unit_error=红` 保持颜色语义梯度。

reporter 现有把 `diff_type` 作为行 class 的逻辑对新枚举无需改动，`tr.field_missing`
类名会自动生效。

## 任务状态与批次聚合

- 单 task 层面：`status="success"`，`comparison_result` 正常生成，`diff_details` 里
  包含 field_missing 汇总记录
- 批次层面：`batch_summary.json` 里该 task 显示为 success，`stats.diff` 包含汇总
  记录数，`batch_summary.html` 里显示为 ✓（而非 ✗）
- CLI 退出码：不变。走正常 `compute_exit_code` 逻辑；`--fail-on-diff` 时 field_missing
  产生的 diff 会让 exit code 变 10

## 测试

### 单元测试

`tests/unit/normalize/test_columns.py`（新增）：
- `test_apply_column_mapping_field_missing_returns_marker` — 缺 field 时返回
  `(df, {"vmemorys"})` 而非 raise
- `test_apply_column_mapping_key_missing_still_raises` — 缺 key 仍抛 `ConfigError`
- `test_apply_column_mapping_multiple_fields_missing_all_reported` — 多字段缺列全部
  进 missing set
- `test_apply_column_mapping_literal_field_untouched` — literal 字段不进 missing
  检测

`tests/unit/normalize/test_pipeline.py`（追加）：
- `test_normalize_side_returns_normalized_side_dataclass` — 签名变更
- `test_normalize_side_skips_normalization_for_missing_fields` — 缺字段的 regex/
  coerce/decimal 不运行
- `test_normalize_side_missing_field_canonicals_propagated` — missing 集合正确传递

`tests/unit/engine/test_memory.py`（追加）：
- `test_field_missing_on_left_produces_summary_diff` — 单字段左缺 → 1 条汇总记录，
  其它字段正常
- `test_field_missing_on_right_produces_summary_diff` — 对称
- `test_field_missing_on_both_sides_raises_config_error` — 双侧同字段缺 →
  `ConfigError`
- `test_field_missing_multiple_fields_ordering_matches_declaration` — 多字段各单侧
  缺，diff 记录按 fields 声明顺序交错
- `test_field_missing_left_only_rows_padded_with_placeholder` — `left_only_rows` /
  `right_only_rows` 补齐 "字段不存在" 列
- `test_field_missing_status_still_success` — 通过 `SubTaskResult` 走完 →
  `status="success"`
- `test_field_missing_matched_rows_and_identical_rows_unchanged` — 统计不受污染

`tests/unit/engine/test_disk.py`（追加）：
- 至少 1 条 parity test：同样 fixture 在 memory/disk 两个 engine 上 diff_details
  长度和 field_missing 计数相等

`tests/unit/reporters/test_html.py`（追加或新建）：
- `test_html_renders_field_missing_row_with_gray_class` — `tr.field_missing` CSS
  类出现

### 集成测试

`tests/integration/test_batch_e2e.py`（追加）：

**Scenario M** — 3-sub-task batch：
- task1：正常成功
- task2：单侧 field 缺列（从 v0.7 的 failed 变成 v0.8 的 success + field_missing
  汇总）
- task3：key 缺列（仍 failed，验证 key 硬失败路径不变）

断言：
- `batch_summary.json` 三个 task 状态分别 success / success / failed
- task2 的 `stats.diff` ≥ 1（至少含那条汇总记录）
- task2 生成了完整 `report.html` / `report.json`
- `batch_summary.html` 里 task2 显示为 ✓ 而不是 ✗

### 回归覆盖

- `test_batch_scenario_l`（v0.7 场景，故意用不存在的 sheet 触发 failed）**必须仍
  然绿** —— sheet 不存在是 loader/reader 阶段的错误，跟 field 缺列不同源，走
  `ConfigError` 硬失败路径不变
- `apply_key_regex` shim 和 key regex 测试不受影响（key 缺列仍走原路径 raise）
- 现有 `apply_column_mapping` 的 tests 若依赖"缺 field 就 raise"，需要迁移到新的
  "缺 field 就上报"语义

### 验证命令

```bash
.venv/Scripts/pytest tests/ -q         # 全绿
.venv/Scripts/ruff check src/ tests/   # 无新增 warning
.venv/Scripts/mypy src/datacompare/    # NormalizedSide 新签名类型正确
```

## 文档

- `README.md`：批次模式小节末尾追加"字段缺列软失败"一段
- `docs/user-guide.md`：新增章节 `### 字段缺列软失败（v0.8+）`
- `CLAUDE.md`：新增两条约束
  - `apply_column_mapping` 对 field 缺列不再 raise，只对 key 缺列 raise；"双侧同
    field 缺"的硬失败判定在 engine 层
  - `NormalizedSide` 是纯数据容器；`normalize_side` 消费方要显式取 `.df`

## 向后兼容

- 老 YAML **无需修改**
- 老行为的破坏面：以前缺 field → task failed（exit 2）；现在缺 field → task
  success + diff 记录（exit 0，或 exit 10 with `--fail-on-diff`）
- 想保持"缺字段就红"语义的用户加 `--fail-on-diff` 即可
- `NormalizedSide` 是新内部类型，`normalize_side` 是内部函数，签名变更不影响
  CLI 用户

## 明确不做的事

- **不加 YAML 开关**：`compare.on_missing_field: fail | soft` 之类的配置。YAGNI，
  单一行为更简单，需要 fail 的用户走 `--fail-on-diff` 已经足够
- **不引入新任务状态**：不加 `success_with_warnings` 或类似——比对确实跑完了就是
  success
- **不做逐行 field_missing 展开**：一个缺列 = 一条汇总记录，不给每个 row 都产生
  一条（会淹没真正的值差异）
- **不做国际化**：`"字段不存在"` 硬编码中文字面量，跟现有中文 HTML 模板一致

## 工作量估算

| 模块 | 行数 |
|---|---|
| `normalize/columns.py` 拆分 | ~20 |
| `normalize/pipeline.py` `NormalizedSide` | ~15 |
| `engine/memory.py` + `engine/disk.py` | ~60 |
| `engine/result.py` `DiffType` 枚举 | ~1 |
| HTML CSS | ~1 |
| 测试 | ~200 |
| 文档 | ~30 |

单 PR，6-8 个 commit（TDD 节奏，每层一个失败测试 → 实现 → 提交）。**无新依赖**。
