# 字面量字段值设计规范

**日期：** 2026-07-20
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划

## 问题背景

比对两个数据源时，用户偶尔会遇到这种情况：某个比对字段在一侧没有对应列，但仍需与另一侧的真实列做比对，且该"缺失侧"应被视为固定常量。批次模式下已出现真实场景：某 Excel sheet 页没有 `zone` 列，但对应的 GaussDB 表有 `type` 列，且期望所有匹配行的 `type` 都等于字符串 `"Azone"`。当前用户只能预处理 Excel 或跳过这项校验。

## 方案概览

在 `FieldRule` 上新增两个可选 Pydantic 字段：`left_literal` 和 `right_literal`。每个持有 `str | None` 值，在 normalize 阶段被广播到该侧的每一行，取代原本的"从源列取值"行为。字面量走完整的每字段转换管线（string 预处理 → unit 换算 → 类型强转 → 精度舍入），所以 `mode: numeric` 等配置对字面量同样生效。

**仅** 比对字段（`FieldRule`）支持字面量。匹配键（`KeyMapping`）**不** 支持——字面量 join key 会造成笛卡尔积，语义无意义。

## YAML 表面

```yaml
compare:
  fields:
    # 现有写法（行为不变）
    - {left: real_col, right: real_col}

    # 新：左侧为常量字符串
    - {left_literal: "Azone", right: type}

    # 新：左侧为字面 null（断言匹配行的右侧列为 null）
    - {left_literal: null, right: deleted_at}

    # 新：右侧为常量（对称支持）
    - {left: name, right_literal: "prod"}

    # 新：字面量 + numeric 模式 → 字面量走同一条转换管线
    - {left_literal: "30", right: memory,
       mode: numeric, decimal_places: 2}
```

## 校验规则

在 `FieldRule` 上加 `@model_validator(mode="after")`：

- 每一侧（`left`、`right`）**必须恰好** 指定 `<side>` 或 `<side>_literal` 其中之一。两者都给 → 报错。都不给 → 报错。
- 判定"是否指定"用 Pydantic v2 的 `model_fields_set`，**不** 用 `value is None` 判定。原因：`left_literal: null`（YAML 显式 null）需要与"根本没写 left_literal"区分。两种情况下 `.left_literal` 的运行时值都是 `None`，但前者在 `model_fields_set` 里、后者不在。
- 允许两侧同时字面量（`{left_literal: "A", right_literal: "A"}`）。这种写法要么永远相等、要么永远不等，本身没意义，但按 YAGNI 原则不加校验。

## 模型改动

`src/datacompare/config/models.py::FieldRule`：

```python
class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str | None = None          # 原：str
    right: str | None = None         # 原：str
    left_literal: str | None = None  # 新增
    right_literal: str | None = None # 新增
    # ... 其余 mode / decimal_places / ... 保持原样

    @model_validator(mode="after")
    def _check_source_specifiers(self):
        for side in ("left", "right"):
            col_set = side in self.model_fields_set
            lit_set = f"{side}_literal" in self.model_fields_set
            if not col_set and not lit_set:
                raise ValueError(
                    f"field must specify '{side}' or '{side}_literal'"
                )
            if col_set and lit_set:
                raise ValueError(
                    f"cannot specify both '{side}' and '{side}_literal'"
                )
        return self
```

**向后兼容：** 现有任何 `{left: "col", right: "col"}` 都能通过（`left` 和 `right` 都在 `model_fields_set` 里，两个 `_literal` 都未设）。老配置行为不变。

## 管线改动

`src/datacompare/normalize/columns.py::apply_column_mapping`：

```python
def apply_column_mapping(df, keys, fields, side):
    rename_map = {}
    for k in keys:
        rename_map[getattr(k, side)] = k.right
    for f in fields:
        src = getattr(f, side)  # 字面量字段这里为 None
        if src is not None:
            rename_map[src] = f.right

    missing = [src for src in rename_map if src not in df.columns]
    if missing:
        raise ConfigError(...)  # 保持不变

    src_cols = list(rename_map.keys())
    result = df[src_cols].rename(columns=rename_map)

    # 新增：把字面量字段作为常量列注入
    for f in fields:
        if getattr(f, side) is None:
            literal_val = getattr(f, f"{side}_literal")
            result[f.right] = literal_val  # pandas 广播标量

    return result
```

**零行 DataFrame：** 空 DataFrame 上做 `result[f.right] = "Azone"` 会得到 object dtype 的空列，不会崩。下游 merge 得零匹配行，符合预期。

**管线注入位置：** 只动 `apply_column_mapping` 一个函数。`pipeline.py` 里的 `normalize_side` 不用改——字面量列注入后跟真实列完全等价，会自然流经 `_process_value`，字段规则里的 `mode` / `null_equivalents` / `parse_unit` 等全部按原有逻辑生效。

**`null_equivalents` 的影响：** 如果用户写 `left_literal: "NULL"` 且 `null_equivalents` 包含 `"NULL"`，字面量会被判为 `None`。想真正传 None 就写 `left_literal: null`。

## 不改动的部分

- `KeyMapping` —— join key 不加 `left_literal` / `right_literal`。
- 引擎层（`memory.py`、`disk.py`）—— merge 与 diff 逻辑不变；传入的规范化 DataFrame 里字面量列已经具象化。
- 报告层 —— 字面量差异的渲染与普通值差异完全一致（`left_value: "Azone"`、`right_value: "Bzone"` 等）。
- 批次模式 —— `fields:` 是 list，按现有规则整体替换，所以子任务用字面量字段覆盖 defaults 时不会产生合并冲突。

## 测试计划

**模型校验**（`tests/unit/config/test_models.py`）：
- `FieldRule(left="a", right="b")` → OK
- `FieldRule(left_literal="X", right="b")` → OK
- `FieldRule(left_literal=None, right="b")` → OK（显式 null 字面量）
- `FieldRule(left="a", right_literal="X")` → OK
- `FieldRule(right="b")` → ValidationError（左侧两个都没给）
- `FieldRule(left="a", left_literal="X", right="b")` → ValidationError

**列注入**（`tests/unit/normalize/test_columns.py`）：
- 带 `left_literal` 的字段调 `apply_column_mapping`：结果里出现同名合成列，值广播到每一行
- side="right" 时 `right_literal` 行为对称
- `left_literal: None` → 该列所有值为 None
- 零行 DataFrame + 字面量 → 空列，无异常

**端到端管线**（`tests/unit/normalize/test_pipeline.py`）：
- `{left_literal: "30", right: "amt", mode: numeric, decimal_places: 2}`，左 DataFrame 无 `amt` 列 → normalize 后左侧 `amt` 全部为 `30.0`
- `{left_literal: null, right: "deleted_at"}` → normalize 后左侧 `deleted_at` 全部为 `None`

**集成**（`tests/integration/test_batch_e2e.py`）：
- 新增批次子任务：左 Excel（无 `type` 列）vs. 右 Excel（`type` 列逐行变化）。断言仅当右侧 `type != literal` 时才产生差异。

## 文档

- `README.md`：在"比对规则"下加"字面量字段"小节，用 YAML 表面部分作示例。
- `docs/user-guide.md`：在"比对模式"章节后加同名小节，附 null 字面量案例和 numeric 强转说明。
- `CLAUDE.md`：在"关键约束"下追加一条，注明字面量特性和 `model_fields_set` 判定技巧（防止后续编辑误用 `is None` 判断从而破坏 null 字面量）。

## 工作量估算

- 模型：约 15 行（2 个字段 + 1 个 validator 方法）
- `apply_column_mapping`：约 8 行（循环 + 注入）
- 测试：3 个文件共约 80 行
- 文档：3 个文件共约 30 行

单 commit、单 PR。无新依赖。
