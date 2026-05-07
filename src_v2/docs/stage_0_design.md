# Stage 0 重设计 — Maude contract 抽取

来源：`walk-pipeline` 走查 Stage 0 + 设计对话 + 自审修订（rev2）。
路线：**A2-a** Lark 子集 parser + **B2-y** unresolved 静默写 contract + **C1-y** 启发式 unmatched 走 stderr。
新代码全部住在 `src_v2/`，与旧 `src/` 平级互不影响。

---

## 0. 范围与硬约束

**修这些**（来自走查 PROGRESS.md）：F0-1 链式 subsort、F0-2 `is_attribute` 误判、F0-3 attribute 广播、F0-4 启发式藏在源码里。

**留 backlog**：F0-5 CLI 化、`Rule.lhs` 改 term tree、Maude `omod/theory/parameterized module`。

**不改的下游契约**（动手前已读 `@/Users/wuyue/0-我的/0-THU/0-网络测绘组/Projects/协议形式化/reproduce/dns-sigcomm/LLM-DNS-RFC/src/maude_generator/registry.py:208-345` 确认）：

- 下游消费的字段：`actors[*].state_interface`、`rules[*].event_pattern`、`rules[*].guard_slots[*].template`、`rules[*].action_slots[*].action_type`、`rules[*].actor_role`。
- 下游 RoleRegistry/EventPatternRegistry 用的是 **substring 匹配** (`alias in lower`，registry.py:57-63)，所以新 contract 的字段值哪怕格式微调，向下兼容弹性比严格 schema 更宽。**但**这层弹性不掩盖 F0-3 修复带来的属性缩水（见 §8 验收）。
- 下游不读 `unresolved` 顶层字段，故新增此字段对 Phase 4a 零影响。

---

## 1. 目录布局

```
src_v2/
├── docs/stage_0_redesign.md          ← 本文档
├── maude_parser/
│   ├── parser/                       ← 纯语法层；禁碰 actor 语义
│   │   ├── grammar.lark
│   │   ├── tree_to_ast.py
│   │   └── maude_parser.py           ← 公开 parse_file / parse_text / MaudeParser
│   ├── semantics/                    ← 读 AST → ActorSemantics
│   │   └── actor_resolver.py
│   ├── exporters/
│   │   ├── json_exporter.py          ← 瘦身: 仅装配, 不推断
│   │   ├── inference.py              ← yaml dispatcher
│   │   ├── config/inference_rules.yaml
│   │   └── dot_exporter.py           ← 从 src/ 移植, 不改逻辑
│   ├── models/
│   │   ├── maude_ast.py              ← 从 src/ 移植
│   │   └── contract.py               ← 移植 + 加 `unresolved` 字段
│   ├── pipeline.py                   ← 接新接口; 文件清单仍硬编码 (F0-5)
│   └── output/                       ← maude_contract.json / maude_tagging.json
└── tests/maude_parser/
    ├── test_parser.py                ← L1
    ├── test_actor_resolver.py        ← L2
    ├── test_inference.py
    ├── test_stage_0_diff.py          ← L3
    └── baselines/
        ├── stage_0_contract.before.json   ← 冻结自 src/.../output/
        └── stage_0_contract.after.json    ← 重写后产生
```

**三层硬边界**：

- `parser/` 输出无损 AST，**禁止**任何 actor / attribute 知识。
- `semantics/` 只读 AST，输出 `ActorSemantics`，**禁止**字符串 regex。
- `exporters/` 读 AST + ActorSemantics，**禁止**新增语义推断（启发式只能查 yaml）。

---

## 2. parser/ — Lark 子集 (A2-a)

### 覆盖

`fmod / mod / endfm / endm`、`sort(s)`、`subsort(s)`（**含链式**，修 F0-1）、`op(s)` 含 mixfix 与属性集 `[ctor assoc comm id: nil prec 10]`、参数化 sort `Foo{X}`、`var(s)`、`eq / ceq`、`rl / crl`、`view`、`pr/inc/ex`、注释 `--- ` 和 `*** `。

**注释边界**：`---` 后必须紧跟空白或行尾才算注释（防止吃掉 `op _---_` 类操作符）。L1 测试覆盖反例。

**不覆盖（backlog）**：`th/endth`、`mod M{X :: TH}`、`omod`。

### 实现

- `grammar.lark`：EBNF 产生式。
- `tree_to_ast.py`：`lark.Transformer` → 既有 `Module/Op/Equation/Rule/View` dataclass（保持下游接口）。
- `maude_parser.py`：导出 `parse_file(path) -> List[Module]`、`MaudeParser` 累计多文件入 `modules: Dict[str, Module]`。
- 解析失败：抛 `MaudeSyntaxError(file, line, col, near_text)`，**不实现 regex fallback**。

### 工作量

**先做 dry-run 探针（动手前 1 小时）**：写一份最小 grammar，把 `Maude/src/common/_aux.maude`（1564 行，模型 65% 体量）整文件喂给 lark Earley 跑，记录所有 ambiguous warning 和 parse error 位置。再据此估真正工作量。

不做 dry-run 直接动手的工作量估计偏低 50–100%，主要风险点：mixfix `_..._` 与属性集 `id:` 共用冒号；`mod ... is` 与 `view ... is` 共用 `is`；`_aux.maude` 的 corner case 集中地。

---

## 3. semantics/actor_resolver.py — B2-y

### 输出

```python
@dataclass
class AttrBinding:
    actor_type: str          # e.g. "Resolver"
    attr_op_name: str        # e.g. "cache:_"
    attr_label: str          # 去掉 :_/:
    param_sort: str
    source_rule_id: Optional[str]  # 第一条印证 binding 的 rule

@dataclass
class ActorSemantics:
    actor_types: List[str]
    attribute_ops: Dict[str, Op]            # coarity == 'Attribute'，不看名字后缀
    bindings: List[AttrBinding]
    unresolved_attribute_ops: List[Op]      # 声明了但未在任何 rule LHS 出现
```

### 算法

1. `actor_types` = `coarity=='ActorType'` 的 nullary op 名（**这条不变**）。
2. `attribute_ops` = `coarity=='Attribute'` 的 op，**与名字是否带 `:_` 无关**——直接消灭 F0-2。
3. 扫 `module.rules[*].lhs` 字符串，匹配 `< <addr_term> : <ActorType> | <attr_op_names> >`，提取 `(actor_type, [attr_op_names])` 对，去重生成 `AttrBinding`——直接消灭 F0-3 的"广播"。
4. `unresolved_attribute_ops = attribute_ops - {b.attr_op_name for b in bindings}`。

### 模式匹配实现

不要回退到 regex 大杂烩。`Rule.lhs` 仍是 `str`（改为结构化 term tree 出本轮 scope）。在 `actor_resolver.py` 内写一个 ~50 行专用 mini tokenizer，**只**识别 `<...:<Identifier>|<comma_seq>>` 这一种模式，其他 LHS 内容忽略。L2 测试覆盖：单 actor、多 actor 同 LHS、无 actor pattern、未在任何 rule LHS 出现的 attribute op。

### B2-y 决策落地

`unresolved_attribute_ops` 写入 `contract.unresolved.attribute_ops`，**不**打 warning，**不**进 metadata。判断 contract 健康度 = 看 `contract.unresolved` 是否非空。

---

## 4. exporters/ — C1-y 改造（**逐方法**清单）

源代码引用：`@/Users/wuyue/0-我的/0-THU/0-网络测绘组/Projects/协议形式化/reproduce/dns-sigcomm/LLM-DNS-RFC/src/maude_parser/exporters/json_exporter.py`。

| 方法 | 当前位置 | 处置 | 备注 |
|---|---|---|---|
| `_extract_sort_contracts` | 56-101 | **保留**（小调整） | 与新 parser AST 对齐 |
| `_extract_actor_contracts` | 103-161 | **重写** | 数据源从 `self.actor_attributes` 切到 `ActorSemantics.bindings`；`state_interface[attr].mode` 调用新 `inference.classify_attr_access(attr_label)` |
| `_extract_rule_contracts` | 163-207 | **保留 guard_slots/action_slots 装配；推断委派给 inference 模块** | guard_slots 仍来自 `rule.condition` 直接复制 (line 182-187)；event_pattern / action_slots / state_reads/writes 改为调用 `inference.*` |
| `_infer_actor_role` | 209-226 | **保留**，重命名为 `_dispatch_actor_role` | 这是装配逻辑（rule → actor_role 字段），不是推断；Phase 4a RoleRegistry 依赖此字段非空。**未来想去掉这条子串匹配**留 backlog |
| `_infer_event_pattern` | 228-242 | **删**，迁到 `inference.infer_event(rule_name)` | 未命中返回 `"unknown_event"` + stderr warning |
| `_infer_state_access` | 244-258 | **删**，迁到 `inference.classify_attr_access(attr_label)` | yaml 写 `write_keywords` 列表，命中升 `read_write` |
| `_infer_action_slots` | 260-279 | **删**，迁到 `inference.infer_action_slots(rule_name, rhs)` | 未命中返回 `[]` + stderr warning |
| `_generate_rule_tags` | 281-305 | **删** | 仅 tagging 体系用，迁到 `inference.tag_rule(...)` |
| `_extract_module_info` / `_extract_sort_hierarchy` / `export_to_json` / `export_tagging_system` / `_contract_to_dict` | 307+ | **保留** | 装配 + 序列化；`_contract_to_dict` 加一行处理新 `unresolved` 字段 |

### `inference_rules.yaml` schema（**统一 list 形式**）

```yaml
event_patterns:
  - if_name_matches: "recv.*query"
    pattern: "recv query(...)"
  - if_name_matches: "recv.*(response|ans)"
    pattern: "recv response(...)"
  - if_name_matches: "recv.*referral"
    pattern: "recv referral(...)"
  - if_name_matches: "start"
    pattern: "init"
  - if_name_matches: "timeout"
    pattern: "timeout"
  # default: "unknown_event"

action_slots:
  - if_rhs_contains_any: ["cache"]
    slot_type: cache_operation
    description: "Update cache with new records"
  - if_rhs_contains_any: ["send", "msg"]
    slot_type: send_message
    description: "Send message to another actor"

state_access:
  write_keywords: [cache, queue, budget, queries, blocked, sent]
```

`if_rhs_contains_any` 统一是 list（即使单值也写成 `["cache"]`）。dispatcher 由 `inference.py` 实现，~80 行。

### C1-y 决策落地

未命中 → 返回缺省值（`"unknown_event"` / `[]`）+ `logging.warning("[Stage0/inference] ...")` 走 stderr。**不**写进 `MaudeContract` 任何字段。可选 `--strict` flag 把 warning 转 error 留 backlog。

### `MaudeContract` schema 调整

`models/contract.py` 加一个 `unresolved: Dict[str, List[str]] = field(default_factory=dict)`。

**已确认下游零影响**：`@/Users/wuyue/.../src/maude_generator/registry.py:310-345` 只读 `actors / rules / sorts / sort_hierarchy`，从未访问 `unresolved`，故新字段可被 Phase 4a 忽略。

---

## 5. pipeline.py 改造

```python
from .parser.maude_parser import MaudeParser
from .semantics.actor_resolver import ActorResolver
from .exporters.json_exporter import JSONExporter

class MaudeParserPipeline:
    def __init__(self):
        self.parser = MaudeParser()
        self.resolver = ActorResolver()

    def parse_files(self, paths):
        for p in paths:
            self.parser.parse_file(p)

    def export_json(self, contract_path, tagging_path=None):
        semantics = self.resolver.resolve(self.parser.modules)
        exporter = JSONExporter(self.parser.modules, semantics)
        exporter.export_to_json(contract_path)
        if tagging_path:
            exporter.export_tagging_system(tagging_path)
```

`main()` 函数体（输入文件清单、输出路径）逐字搬过来，仅把 `../../Maude/src` 路径相对解析到 `src_v2/` 自己的位置。F0-5 不动。

---

## 6. 测试设计

### L1 — `test_parser.py`

`pytest.mark.parametrize` 内联 maude 片段 ~12 例：

- F0-1 回归：`subsort A < B C .` → 2 条 subsort
- mixfix op 名含 `:` `.` `_`：`op _._ : ...`、`op to_:_ : ...`
- `ceq ... if ...` / `crl [...] : ... => ... if ... .`
- `view V from A to B is ... endv`
- 参数化 sort `Foo{X}`
- 注释边界：`op _---_ : ...` **不**被注释吃掉
- 模块导入 `pr A + B`（split 成 2 条）
- 解析失败抛 `MaudeSyntaxError`

### L2 — `test_actor_resolver.py`

**绕过 parser**，直接构造 `Module/Op/Rule` dataclass 实例喂给 `ActorResolver.resolve(...)`。这样 L1 / L2 解耦，可并行迭代。

覆盖：

- 单 actor 单 attribute LHS
- 多 actor 同 LHS
- 无 actor pattern LHS（应返回空 bindings）
- attribute op 在 `eq` 而非 `rl` 的 lhs 出现 → 仍归 unresolved（约定：归属信息**只**来自 rule LHS）
- F0-2 回归：构造一个 `op to_:_ : ... -> Msg` 的 op，确认它**不**进 `attribute_ops`

### L2.5 — `test_inference.py`

短小：每条 yaml 规则 1-2 个例子，外加未命中 → 走 warning 路径的断言（用 `caplog` 捕获 stderr）。

### L3 — `test_stage_0_diff.py`

1. **动手第一步先冻结 baseline**：
   ```
   cp src/maude_parser/output/maude_contract.json \
      src_v2/tests/maude_parser/baselines/stage_0_contract.before.json
   ```
2. 重写完成后跑 `python -m maude_parser.pipeline`（从 `src_v2/` 内）→ 产出新 `output/maude_contract.json` → 复制为 `stage_0_contract.after.json`。
3. 用 `deepdiff` 比 before/after，断言所有差异**只**落在以下白名单类别：
   - 新增 subsort 条目（F0-1）
   - 从 `actors[*].state_interface` 中**消失**被误判的 attribute（F0-2）
   - `actors[*].state_interface` 总体缩小（F0-3 真实化，预期且必要）
   - 新增 `unresolved` 顶层字段（B2-y）

任何不在白名单内的 diff → 测试失败。

---

## 7. 实施步骤

1. **冻结 baseline**：复制旧 contract 到 `src_v2/tests/maude_parser/baselines/stage_0_contract.before.json`。
2. **Lark dry-run 探针**（§2 末尾）：1 小时；据结果再排期。
3. 移植 `models/maude_ast.py` 到 `src_v2/`，同时给 `models/contract.py` 加 `unresolved` 字段。
4. 写 `grammar.lark` + `tree_to_ast.py` + L1 测试 → L1 全绿。
5. 写 `actor_resolver.py` + L2 测试（**绕过 parser**） → L2 全绿。
6. 写 `inference_rules.yaml` + `inference.py` + L2.5 测试。
7. 写 `json_exporter.py`（按 §4 表格逐方法处置）+ 移植 `dot_exporter.py`。
8. 写 `pipeline.py`，跑一次产出 `output/maude_contract.json`，复制为 `stage_0_contract.after.json`。
9. 跑 L3 → 全绿。
10. **跨目录 demo 验证**（§8 验收）。
11. 更新走查 `src/tests/walkthrough/PROGRESS.md`：把 F0-1/2/3/4 标 ✅，F0-5 留挂；补一行指向 `src_v2/` 实施完成。
12. 重跑走查 probe `src/tests/walkthrough/stage_0_maude_contract.py`（**针对旧代码**），其行为无变化（旧代码没动）；新行为通过 `src_v2/` 自己的 demo 与 L3 验证。

---

## 8. 验收标准

- [ ] L1 / L2 / L2.5 / L3 全绿。
- [ ] `python -m maude_parser.pipeline`（从 `src_v2/`）跑通，产物 `src_v2/maude_parser/output/maude_contract.json` 文件存在。
- [ ] **L3 diff 白名单干净通过**（无未预期变化）。
- [ ] **跨目录 demo 验证（P0-2 修复）**：用配置覆盖把 `src/main.py` 的 `contract_path` 指向 `src_v2/maude_parser/output/maude_contract.json`，跑一次完整 demo（`python main.py` 等价命令），记录：
  - `unresolved` 数量与字段分布 vs before baseline；
  - 增量应主要落在 `field_name == "attribute"`（因 F0-3 真实化，原本被广播的属性现在 unresolve 了）；
  - 不应在 `field_name == "role"` / `event` / `action` 出现新 unresolve（因下游 substring 匹配仍能 match 现有词表）。
  - 出现意外 unresolve 类别 → 视为重写未通过，回到 §4 表格审视哪个方法处置错了。
- [ ] `src_v2/maude_parser/output/maude_contract.json` 体积、模块数、actor 数与 before baseline 在预期差异范围内（attribute 总数下降、其余字段持平）。
- [ ] 走查 probe `src/tests/walkthrough/stage_0_maude_contract.py` 仍跑通且输出未变（说明旧代码未被误伤）。

---

## 9. 不在本设计内（backlog）

- F0-5：`pipeline.py main()` 文件清单 → CLI / yaml。
- `Rule.lhs` 字符串 → 结构化 term tree（这一改动会让 `actor_resolver` 模式匹配从 mini tokenizer 升级到 tree 匹配，更鲁棒；但 scope 太大）。
- `_dispatch_actor_role` 的子串匹配 → 走 yaml 或基于 `actor_resolver.bindings` 反查（更准）。
- Maude `omod / theory / parameterized module` 支持。
- contract `--strict` flag：让 inference warning 转 error，CI 友好。
