# Sheet 名正则唯一匹配 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `SheetSelector` 加第三种选择方式 `name_regex`，用 `re.fullmatch` 唯一匹配一张 sheet；0 或 ≥2 命中 → `ConfigError`。

**Architecture:** `SheetSelector` 新增 `name_regex: str | None` 字段，`@model_validator` 强制三选一并加载期 `re.compile` 校验；`_selected_sheet_names` 加新分支跑 `pattern.fullmatch(name)`，命中数不为 1 时抛 `ConfigError`。

**Tech Stack:** Python 3.11+ / pydantic v2 / openpyxl / re / pytest

**规范来源:** `docs/superpowers/specs/2026-07-27-sheet-name-regex-design.md`

---

## 文件结构

| 文件 | 变化类型 | 责任 |
|---|---|---|
| `src/datacompare/config/models.py` | 修改 | `SheetSelector` 加 `name_regex` 字段 + `@model_validator` 三选一 + 加载期 regex 编译校验 |
| `src/datacompare/sources/excel.py` | 修改 | `_selected_sheet_names` 加 `name_regex` 分支，跑 `re.fullmatch` 严格唯一 |
| `tests/unit/config/test_models.py` | 追加 | 6 个 SheetSelector validator 测试 |
| `tests/unit/sources/test_excel.py` | 追加 | 5 个 excel 源 name_regex 测试 |
| `tests/integration/test_batch_e2e.py` | 追加 | Scenario N e2e |
| `README.md` | 修改 | Excel 数据源速查节加 name_regex 用法 |
| `docs/user-guide.md` | 修改 | Excel 章节加"关键字/正则匹配 sheet"小节 |

---

## Task 依赖顺序

1. Task 1: `SheetSelector` 模型扩展 + validator（独立，最先）
2. Task 2: Excel 源运行时 regex 匹配（依赖 Task 1 的字段）
3. Task 3: Integration Scenario N（依赖 Task 1 + Task 2）
4. Task 4: 文档（可最后，纯 markdown）

每个 Task 结束系统仍全绿。

---

### Task 1: `SheetSelector` 加 `name_regex` 字段 + 三选一 validator

**Files:**
- Modify: `src/datacompare/config/models.py`（`SheetSelector` 类）
- Test: `tests/unit/config/test_models.py`（append 6 tests）

- [ ] **Step 1: 写失败测试 — name_regex 单纯合法**

追加到 `tests/unit/config/test_models.py`：

```python
def test_sheet_selector_name_regex_valid():
    """v0.9: 单纯 name_regex 是合法的（三选一之一）。"""
    sel = SheetSelector(name_regex=r"^物理主机_\d{4}_\d{2}$")
    assert sel.name_regex == r"^物理主机_\d{4}_\d{2}$"
    assert sel.name is None
    assert sel.index is None


def test_sheet_selector_exclusive_name_and_regex():
    """同时给 name + name_regex → ValidationError。"""
    with pytest.raises(ValidationError):
        SheetSelector(name="A", name_regex="^A.*")


def test_sheet_selector_exclusive_index_and_regex():
    """同时给 index + name_regex → ValidationError。"""
    with pytest.raises(ValidationError):
        SheetSelector(index=0, name_regex="^A.*")


def test_sheet_selector_all_three_provided():
    """三个都给 → ValidationError。"""
    with pytest.raises(ValidationError):
        SheetSelector(name="A", index=0, name_regex="^A.*")


def test_sheet_selector_none_of_three():
    """全空 → ValidationError。"""
    with pytest.raises(ValidationError):
        SheetSelector()


def test_sheet_selector_regex_compile_check_load_time():
    """非法 pattern 在加载期就报错，不到运行时才炸。"""
    with pytest.raises(ValidationError) as excinfo:
        SheetSelector(name_regex="[unclosed")
    assert "invalid name_regex" in str(excinfo.value) or "unterminated" in str(excinfo.value).lower()


def test_sheet_selector_regex_with_inline_flag_compiles():
    """(?i) inline flag 合法编译。"""
    sel = SheetSelector(name_regex="(?i)^physical_host_.*")
    assert sel.name_regex.startswith("(?i)")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py::test_sheet_selector_name_regex_valid -v`
Expected: FAIL — `SheetSelector.__init__() got an unexpected keyword argument 'name_regex'`

- [ ] **Step 3: 修改 `src/datacompare/config/models.py`**

当前 `SheetSelector`（约第 8-11 行）：
```python
class SheetSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    index: int | None = None
```

顶部 imports 加：
```python
import re
from pydantic import model_validator
```
（`model_validator` 若已 import 则跳过；`re` 是标准库，直接加）

替换 `SheetSelector` 为：

```python
class SheetSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    index: int | None = None
    name_regex: str | None = None    # v0.9+

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

- [ ] **Step 4: 运行新测试确认通过**

Run: `.venv/Scripts/pytest tests/unit/config/test_models.py -v -k sheet_selector`
Expected: 6 个新测试 + 已有 test_excel_source_defaults 全 PASS

- [ ] **Step 5: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿。注意 `test_excel_source_defaults` 断言 `sheets == [SheetSelector(index=0)]`——`index=0` 是三选一，validator 通过。若断言用了空 `SheetSelector()` 参数才会挂——检查代码没有这样的用法。

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/config/models.py tests/unit/config/test_models.py
git commit -m "$(cat <<'EOF'
feat(config): SheetSelector.name_regex — 三选一 + 加载期 re.compile 校验

v0.9: SheetSelector 新增 name_regex 字段，与 name/index 三选一。
model_validator 强制 provided == 1，且非空的 name_regex 立即用 re.compile
试跑，非法 pattern 加载期就报 ValidationError 而不是到运行时才炸。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Excel 源运行时 `name_regex` 匹配

**Files:**
- Modify: `src/datacompare/sources/excel.py`（`_selected_sheet_names`）
- Test: `tests/unit/sources/test_excel.py`（append 5 tests）

- [ ] **Step 1: 写失败测试 — 唯一命中**

追加到 `tests/unit/sources/test_excel.py`。**先补一个 module-level fixture** 用于 name_regex 测试的多 sheet 文件（如果之前 `_make_fixtures` 里没有类似的）：

```python
@pytest.fixture
def dated_sheets_xlsx(tmp_path):
    """3-sheet Excel with date-suffixed names for name_regex tests."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "物理主机_2026_07"
    ws1.append(["id", "name"])
    ws1.append(["p1", "host-1"])
    ws2 = wb.create_sheet("云主机_2026_07")
    ws2.append(["id", "name"])
    ws2.append(["v1", "vm-1"])
    ws3 = wb.create_sheet("存储_2026_07")
    ws3.append(["id", "name"])
    ws3.append(["s1", "disk-1"])
    p = tmp_path / "dated.xlsx"
    wb.save(p)
    return p


def test_excel_source_name_regex_unique_match(dated_sheets_xlsx):
    """正则唯一命中 → 返回该 sheet 的数据。"""
    cfg = ExcelSourceConfig(
        path=str(dated_sheets_xlsx),
        sheets=[SheetSelector(name_regex=r"^物理主机_\d{4}_\d{2}$")],
    )
    src = ExcelSource(cfg)
    df = pd.concat(src.read())
    assert len(df) == 1
    assert df.iloc[0]["id"] == "p1"
    assert set(df["__sheet__"].unique()) == {"物理主机_2026_07"}
    src.close()


def test_excel_source_name_regex_zero_match_raises(dated_sheets_xlsx):
    """0 命中 → ConfigError，suggestion 列出可用 sheet。"""
    from datacompare.config.errors import ConfigError
    cfg = ExcelSourceConfig(
        path=str(dated_sheets_xlsx),
        sheets=[SheetSelector(name_regex=r"^数据库_\d{4}_\d{2}$")],
    )
    src = ExcelSource(cfg)
    with pytest.raises(ConfigError) as excinfo:
        src.columns()
    msg = str(excinfo.value)
    assert "matched no sheets" in msg
    # suggestion 应含所有可用 sheet 名之一
    assert "物理主机_2026_07" in msg
    src.close()


def test_excel_source_name_regex_multi_match_raises(dated_sheets_xlsx):
    """≥2 命中 → ConfigError，message 列出所有命中项。"""
    from datacompare.config.errors import ConfigError
    cfg = ExcelSourceConfig(
        path=str(dated_sheets_xlsx),
        sheets=[SheetSelector(name_regex=r".+_2026_07$")],   # 会命中 3 张
    )
    src = ExcelSource(cfg)
    with pytest.raises(ConfigError) as excinfo:
        src.columns()
    msg = str(excinfo.value)
    assert "matched 3 sheets" in msg
    assert "物理主机_2026_07" in msg
    assert "云主机_2026_07" in msg
    assert "存储_2026_07" in msg
    src.close()


def test_excel_source_name_regex_case_insensitive_via_flag(tmp_path):
    """(?i) inline flag 让匹配大小写不敏感。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "PHYSICAL_HOST"
    ws.append(["id", "name"])
    ws.append(["1", "a"])
    p = tmp_path / "upper.xlsx"
    wb.save(p)

    cfg = ExcelSourceConfig(
        path=str(p),
        sheets=[SheetSelector(name_regex="(?i)^physical_host$")],
    )
    src = ExcelSource(cfg)
    df = pd.concat(src.read())
    assert set(df["__sheet__"].unique()) == {"PHYSICAL_HOST"}
    src.close()


def test_excel_source_mixed_selectors(dated_sheets_xlsx):
    """一个 sheets 列表里 name + name_regex + index 三种混用。"""
    cfg = ExcelSourceConfig(
        path=str(dated_sheets_xlsx),
        sheets=[
            SheetSelector(name="云主机_2026_07"),                # 精确
            SheetSelector(name_regex=r"^物理主机_\d{4}_\d{2}$"),  # 正则唯一
            SheetSelector(index=2),                                # 索引（第 3 张 = 存储）
        ],
    )
    src = ExcelSource(cfg)
    df = pd.concat(src.read())
    # 3 张 sheet 各 1 行，共 3 行
    assert len(df) == 3
    assert set(df["__sheet__"].unique()) == {
        "云主机_2026_07", "物理主机_2026_07", "存储_2026_07",
    }
    src.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/pytest tests/unit/sources/test_excel.py::test_excel_source_name_regex_unique_match -v`
Expected: FAIL — 当前 `_selected_sheet_names` 没有 `name_regex` 分支，掉进 `else: raise ConfigError("SheetSelector must have name or index")`（现在会挂）

- [ ] **Step 3: 修改 `src/datacompare/sources/excel.py`**

顶部 imports 加：
```python
import re
import structlog

_log = structlog.get_logger(__name__)
```

替换 `_selected_sheet_names`（约第 25-42 行）为：

```python
    def _selected_sheet_names(self) -> list[str]:
        wb = self._open()
        result: list[str] = []
        for sel in self.config.sheets:
            if sel.name is not None:
                if sel.name not in wb.sheetnames:
                    raise ConfigError(
                        f"sheet '{sel.name}' not found",
                        suggestion=f"available: {wb.sheetnames}",
                    )
                result.append(sel.name)
            elif sel.index is not None:
                if sel.index >= len(wb.sheetnames):
                    raise ConfigError(f"sheet index {sel.index} out of range")
                result.append(wb.sheetnames[sel.index])
            elif sel.name_regex is not None:
                pattern = re.compile(sel.name_regex)
                matches = [n for n in wb.sheetnames if pattern.fullmatch(n)]
                if len(matches) == 0:
                    raise ConfigError(
                        f"name_regex '{sel.name_regex}' matched no sheets",
                        path="sources.sheets",
                        suggestion=f"available: {wb.sheetnames}",
                    )
                if len(matches) > 1:
                    raise ConfigError(
                        f"name_regex '{sel.name_regex}' matched {len(matches)} sheets: {matches}",
                        path="sources.sheets",
                        suggestion="tighten the pattern to match exactly one sheet",
                    )
                _log.info(
                    "sheet_regex_resolved",
                    regex=sel.name_regex,
                    resolved_to=matches[0],
                )
                result.append(matches[0])
            else:
                # 不可达：validator 已强制三选一
                raise ConfigError("SheetSelector must have name, index, or name_regex")
        return result
```

- [ ] **Step 4: 运行 excel 测试**

Run: `.venv/Scripts/pytest tests/unit/sources/test_excel.py -v`
Expected: 全绿（5 个新测试 + 已有测试都通过）

- [ ] **Step 5: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add src/datacompare/sources/excel.py tests/unit/sources/test_excel.py
git commit -m "$(cat <<'EOF'
feat(sources/excel): name_regex 分支 — re.fullmatch 严格唯一匹配

_selected_sheet_names 新增 name_regex 分支：跑 pattern.fullmatch(name)，
0 命中或 ≥2 命中都抛 ConfigError（分别列出可用 sheet / 命中项）。混合选
择器（name + name_regex + index）在同一 sheets 列表里各自解析后合并。
支持 (?i) inline flag 忽略大小写。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Integration Scenario N — 批次模式下的 sheet regex

**Files:**
- Test: `tests/integration/test_batch_e2e.py`（append Scenario N）

- [ ] **Step 1: 写 Scenario N 测试**

追加到 `tests/integration/test_batch_e2e.py` 末尾：

```python
def test_batch_scenario_n_sheet_name_regex(tmp_path):
    """v0.9 Scenario N: 批次模式下用 name_regex 定位一张日期戳变名的 sheet。
    - Excel 有 3 张 sheet：物理主机_2026_07 / 云主机_2026_07 / 存储_2026_07
    - batch.yaml 用 name_regex "^物理主机_\\d{4}_\\d{2}$" 定位第一张
    - 断言 sub-task 成功、__sheet__ 列值正确
    """
    _make_xlsx(tmp_path / "manage.xlsx", {
        "物理主机_2026_07": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
        "云主机_2026_07": [["id", "name"], ["v1", "vm-1"]],
        "存储_2026_07": [["id", "name"], ["s1", "disk-1"]],
    })
    _make_xlsx(tmp_path / "snapshot.xlsx", {
        "PHYSICAL": [["id", "name"], ["p1", "host-1"], ["p2", "host-2"]],
    })

    task = tmp_path / "batch.yaml"
    task.write_text(f"""
name: scenario_n
sources:
  left: {{type: excel, path: {tmp_path}/manage.xlsx}}
output:
  dir: {tmp_path}/reports
  formats: [json]
tasks:
  - name: physical_via_regex
    sources:
      left: {{sheets: [{{name_regex: "^物理主机_\\\\d{{4}}_\\\\d{{2}}$"}}]}}
      right: {{type: excel, path: {tmp_path}/snapshot.xlsx, sheets: [{{name: PHYSICAL}}]}}
    match: {{keys: [{{left: id, right: id}}]}}
    compare: {{fields: [{{left: name, right: name}}]}}
""", encoding="utf-8")

    result = runner.invoke(app, ["run", str(task), "--connections", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0, f"stdout={result.output}"

    summary_json = tmp_path / "reports" / "batch_summary.json"
    assert summary_json.exists()
    data = json.loads(summary_json.read_text(encoding="utf-8"))
    assert data["success_count"] == 1
    task_entry = data["tasks"][0]
    assert task_entry["name"] == "physical_via_regex"
    assert task_entry["status"] == "success"
    # 匹配到 2 行 physical_host + 0 diff
    assert task_entry["stats"]["matched"] == 2
    assert task_entry["stats"]["diff"] == 0

    # sub-task 的 report.json 里 __sheet__ 列应指向解析出的实际 sheet 名
    report_json = tmp_path / "reports" / "physical_via_regex" / "report.json"
    assert report_json.exists()
```

**注意**：YAML 里嵌 regex 的反斜杠需要转义两次：
- Python 字符串 `"^\\d{4}"` → 写入文件里的字面是 `^\d{4}`
- Python `f"""..."""` 里再多一层转义：`"^\\\\d{4}"` → 写入文件是 `^\d{4}` → YAML 解析为 `^\d{4}`
- 相同处理花括号：`{{4}}` 转义 f-string 大括号，最终 YAML 是 `{4}`

- [ ] **Step 2: 运行 Scenario N**

Run: `.venv/Scripts/pytest tests/integration/test_batch_e2e.py::test_batch_scenario_n_sheet_name_regex -v`
Expected: PASS

若 FAIL 且错误是 YAML 转义相关（正则被误解析），先在 `task.write_text` 之前 print YAML 内容确认字面对：
```python
print(task.read_text(encoding="utf-8"))
```

- [ ] **Step 3: 现有集成测试回归**

Run: `.venv/Scripts/pytest tests/integration/ -q`
Expected: 全绿

- [ ] **Step 4: 全量回归**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_batch_e2e.py
git commit -m "$(cat <<'EOF'
test(integration): batch scenario N — sheet name_regex e2e

3-sheet Excel（3 个 sheet 都是 XX_2026_07 命名），batch.yaml 用 name_regex
"^物理主机_\d{4}_\d{2}$" 定位第一张。断言 CLI exit 0、batch_summary.json
显示 success + matched=2、生成的 report 里 __sheet__ 列指向解析后的实际
sheet 名。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 文档 — README + user-guide

**Files:**
- Modify: `README.md`（Excel 数据源速查节）
- Modify: `docs/user-guide.md`（Excel 章节新增小节）

- [ ] **Step 1: 用 Grep 定位 README 的 Excel 数据源速查节**

Run: `grep -n "\*\*Excel\*\*" README.md` 或 `grep -n "type: excel" README.md`

期望找到形如：
```
**Excel**（`type: excel`）
```yaml
sources:
  left:
    type: excel
    path: ./data.xlsx
    sheets: [{name: Sheet1}]     # 或 [{index: 0}]
    header_row: 1
    force_string: true
```

- [ ] **Step 2: 在 README.md 的 Excel 速查节末尾追加**

在 Excel 数据源示例 YAML 之后（`force_string: true` 那段之后）追加：

```markdown

**sheet 选择器**（`sheets:` 列表元素三选一）：
- `{name: "PHYSICAL_HOST"}` — 精确匹配
- `{index: 0}` — 按索引（0-based）
- `{name_regex: "^物理主机_\\d{4}_\\d{2}$"}` — 正则唯一匹配（v0.9+）；
  匹配 0 张或 ≥2 张都会 `ConfigError`。适合 sheet 名带日期戳、版本号等
  易变部分的场景。忽略大小写用内联 flag：`(?i)physical_.*`
```

- [ ] **Step 3: 在 `docs/user-guide.md` 的 Sources 章节新增小节**

用 Grep 找 `## Sources` 位置。在 Excel 相关描述之后（或整个 Sources 节的末尾）插入：

```markdown

### Sheet 选择（Excel 专属）

Excel 数据源的 `sheets:` 列表每一项恰好指定 `name` / `index` / `name_regex` 三者之一：

| 字段 | 用途 | 例子 |
|---|---|---|
| `name` | 精确匹配 sheet 名 | `{name: "PHYSICAL"}` |
| `index` | 按位置索引（0-based）| `{index: 0}` |
| `name_regex` | 正则唯一匹配（v0.9+）| `{name_regex: "^物理主机_\\d{4}_\\d{2}$"}` |

`name_regex` 规则：
- 用 Python `re.fullmatch`（整字匹配，不是子串搜索）
- **严格唯一**：0 或 ≥2 命中都抛 `ConfigError` 并列出可用/命中项
- 加载期 pydantic 会试跑 `re.compile`，非法 pattern 立即报错
- 忽略大小写用内联 flag：`(?i)^physical_.*`
- 一个 `sheets:` 列表里可混合三种选择器
```

- [ ] **Step 4: 快速验证文档格式**

Run: `.venv/Scripts/pytest tests/ -q`
Expected: 全绿（文档变更不影响测试）

- [ ] **Step 5: Commit**

```bash
git add README.md docs/user-guide.md
git commit -m "$(cat <<'EOF'
docs: v0.9 sheet name_regex — README + user-guide

README Excel 速查节列出 sheets 三种选择器格式；user-guide 新增 "Sheet
选择（Excel 专属）" 小节说明 name/index/name_regex 用法差异、严格唯一
语义、(?i) inline flag、混合选择器。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## 完成后总校验

- [ ] 全量测试：`.venv/Scripts/pytest tests/ -q` → 全绿（预期 350+ passed / 2 skipped）
- [ ] Lint：`.venv/Scripts/ruff check src/ tests/` → 无新增 error
- [ ] 类型：`.venv/Scripts/mypy src/datacompare/` → 无新增 error
- [ ] 手动烟测：拿一个多 sheet Excel，写 `sheets: [{name_regex: "^X.*"}]`（唯一命中）跑 `datacompare validate task.yaml` + `datacompare run task.yaml`，确认正确定位到 sheet
