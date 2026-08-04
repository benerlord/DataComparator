# Sheet 名正则唯一匹配设计规范

**日期：** 2026-07-27
**状态：** 已批准，进入实现
**范围：** 单 PR / 单实现计划
**目标版本：** v0.9

## 问题背景

批次模式（v0.4+）下，`batch.yaml` 每个 sub-task 的
`sources.left.sheets` 需要写出精确的 sheet 页名称。若源 Excel 的 sheet
命名带日期戳、版本号等易变部分（如 `物理主机_2026_07`），YAML 每次都要
跟着改。用户希望："关键字模糊匹配 + 唯一命中"—— 用一个稳定的正则表达式
定位一张变名字的 sheet。

**典型场景**：`manage.xlsx` 有三张 sheet：
```
物理主机_2026_07
云主机_2026_07
存储_2026_07
```
每月表名的日期部分会变。YAML 里写 `name_regex: "^物理主机_\\d{4}_\\d{2}$"`
一次搞定，跨月不用改。

## 方案概览

`SheetSelector` 加入第三种选择方式 `name_regex`，与既有的 `name`（精确
匹配）和 `index`（按索引）三选一：

- **算法**：`re.fullmatch`（跟项目其它 regex 语义一致）
- **唯一性**：0 或 ≥2 命中 → `ConfigError`，明确列出可用/命中项
- **加载期校验**：pydantic 验证时试 `re.compile`，非法 pattern 立即报错
- **大小写**：默认区分（原生 `re` 语义），需忽略大小写用内联 flag `(?i)`

## `SheetSelector` 扩展

`src/datacompare/config/models.py`：

```python
import re
from pydantic import BaseModel, ConfigDict, model_validator


class SheetSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    index: int | None = None
    name_regex: str | None = None    # v0.9+ 新增

    @model_validator(mode="after")
    def _exactly_one(self):
        provided = sum(x is not None for x in (self.name, self.index, self.name_regex))
        if provided != 1:
            raise ValueError(
                "SheetSelector must have exactly one of: name, index, name_regex"
            )
        # 加载期校验 regex 可编译
        if self.name_regex is not None:
            try:
                re.compile(self.name_regex)
            except re.error as e:
                raise ValueError(f"invalid name_regex '{self.name_regex}': {e}") from e
        return self
```

**互斥规则**：三者恰好一个非 None。加载期就 fail，不到运行时才炸。

## YAML 示例

```yaml
sources:
  left:
    type: excel
    path: manage.xlsx
    sheets:
      - {name: "PHYSICAL_HOST"}                # 精确（不变）
      - {index: 2}                              # 按索引（不变）
      - {name_regex: "^物理主机_\\d{4}_\\d{2}$"} # 正则唯一匹配（新）
```

**混用**：一个 `sheets:` 列表里可任意混合三种选择器；顺序无关，最终产物
是解析后的 sheet 名列表。已有的多 sheet 合并读取逻辑（header 一致性
校验、`__sheet__` 列注入）不改。

## 运行时匹配

`src/datacompare/sources/excel.py::_selected_sheet_names` 加入
`name_regex` 分支：

```python
elif sel.name_regex is not None:
    pattern = re.compile(sel.name_regex)
    matches = [n for n in wb.sheetnames if pattern.fullmatch(n)]
    if len(matches) == 0:
        raise ConfigError(
            f"name_regex '{sel.name_regex}' matched no sheets",
            path=f"sources.sheets",
            suggestion=f"available: {wb.sheetnames}",
        )
    if len(matches) > 1:
        raise ConfigError(
            f"name_regex '{sel.name_regex}' matched {len(matches)} sheets: {matches}",
            path=f"sources.sheets",
            suggestion="tighten the pattern to match exactly one sheet",
        )
    result.append(matches[0])
```

**日志事件**：INFO 级别 emit
```
event=sheet_regex_resolved regex="^物理主机_\d{4}_\d{2}$" resolved_to="物理主机_2026_07"
```
方便 debug"到底命中了哪张 sheet"。

## 大小写

默认区分（`re.fullmatch` 原生语义）。想忽略大小写用内联 flag：

```yaml
sheets:
  - {name_regex: "(?i)^physical_host_.*"}
```

跟项目其它 regex 用法（`KeyMapping.left_regex` 等）一致。

## 批次模式交互

`SheetSelector` 是 `sheets` 列表里的元素。批次 defaults 深度合并规则里
**list 是整体替换**（不合并），所以每个 sub-task 的 `sheets:` 自成一
体，`name_regex` 不受批次层级影响。

## 边界情况

| 情况 | 行为 |
|---|---|
| `sheets` 里同一 pattern 出现两次 | 两次都触发匹配、都追加同名 sheet → 现有 header 一致性检查会通过（同一 sheet），多 sheet 合并读会重复行。不做特殊处理（跟当前 `name: X` 写两次的行为一致） |
| pattern 命中含空格的 sheet 名 | 无差别，`re.fullmatch` 对空白无特殊处理 |
| pattern 是空串 `""` | `re.compile("")` 合法；`fullmatch("")` 只匹配空字符串，通常 0 命中 → `ConfigError` |
| pattern 命中隐藏/被删的 sheet | openpyxl 读到什么就匹配什么，不做过滤 |
| GaussDB / API 数据源 | 不受影响。`name_regex` 仅对 Excel 生效 |

## 测试

### 单元测试

`tests/unit/config/test_models.py`（追加）：
- `test_sheet_selector_name_regex_valid` — 单纯 `name_regex` 合法
- `test_sheet_selector_exclusive_name_and_regex` — 同时给 `name` + `name_regex` → ValueError
- `test_sheet_selector_exclusive_index_and_regex` — 同时给 `index` + `name_regex` → ValueError
- `test_sheet_selector_none_of_three` — 全空 → ValueError
- `test_sheet_selector_regex_compile_check` — 非法 pattern 如 `"[unclosed"` → ValueError at load
- `test_sheet_selector_regex_with_inline_flag` — `"(?i)PHYSICAL"` 合法编译

`tests/unit/sources/test_excel.py`（追加）：
- `test_excel_source_name_regex_unique_match` — 正则唯一命中 → 返回该 sheet
- `test_excel_source_name_regex_zero_match_raises` — 0 命中 → `ConfigError`，
  suggestion 里列出所有可用 sheet
- `test_excel_source_name_regex_multi_match_raises` — ≥2 命中 → `ConfigError`，
  message 里列出所有命中项
- `test_excel_source_name_regex_case_insensitive_via_flag` — `(?i)` inline
  flag 正常工作
- `test_excel_source_mixed_selectors` — 一个 `sheets` 列表里
  `name` + `name_regex` + `index` 混用，各自解析后合并进结果

### 集成测试

`tests/integration/test_batch_e2e.py`（追加 Scenario N）：
- 3-sheet Excel：`物理主机_2026_07`、`云主机_2026_07`、`存储_2026_07`
- batch.yaml 用 `name_regex: "^物理主机_\\d{4}_\\d{2}$"` 定位第一张
- 断言：sub-task 成功、生成 report、比对结果里 `__sheet__` 列值 =
  `物理主机_2026_07`

### 回归

- 现有 `SheetSelector` 用法（只 `name` 或只 `index`）不变
- 现有 Excel 数据源多 sheet 合并读逻辑不受影响

### 验证命令

```bash
.venv/Scripts/pytest tests/ -q         # 全绿
.venv/Scripts/ruff check src/ tests/   # 无新增 warning
```

## 文档

- `README.md`：Excel 数据源速查节追加 `name_regex` 用法示例
- `docs/user-guide.md`：Excel 章节加"关键字/正则匹配 sheet"小节
- `CLAUDE.md`：**无需新约束**（SheetSelector 三选一规则由 pydantic
  validator 内聚，运行期 excel.py 内的分支是纯派生行为）

## 向后兼容

- 新字段 `name_regex` 可选（默认 None），老 YAML 无需修改
- `SheetSelector` 已用 `ConfigDict(extra="forbid")`，加了字段后现有
  `{name: X}` / `{index: Y}` 仍合法
- 无 API 破坏面

## 明确不做的事

- **不支持"匹配全部"语义**：本 spec 只做"唯一命中"。想读多张匹配的
  sheet，仍需在 `sheets:` 里写多条 `name_regex`（一条 pattern 一张
  sheet），或多条精确 `name`。改成"多命中即读多张"会与
  `SheetSelector` 一对一语义冲突，需单独设计
- **不支持编辑距离/token 相似度**：YAGNI；如果确有拼写误差场景再单开
- **不引入 rapidfuzz 等新依赖**
- **不做 sheet 名规范化**（trim 空格、去 BOM 等）：如果源文件带空格
  应在 pattern 里精确表达

## 工作量估算

| 模块 | 行数 |
|---|---|
| `config/models.py` 加字段 + validator | ~20 |
| `sources/excel.py` regex 分支 | ~15 |
| 测试（单元 + 集成 + 参数化）| ~120 |
| 文档（README + user-guide）| ~15 |

单 PR，4-5 commits（TDD 节奏）。**无新依赖**。
