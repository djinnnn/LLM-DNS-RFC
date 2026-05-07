# walk-pipeline · PROGRESS

逐 stage 走查的导航文件。每个 stage 完结后更新一次。引用过期需要在同一回合内修正。

---

## Stage 0 — Maude contract 抽取  ✅ (走查完毕；重设计方案已定，待动手)

**重设计文档（rev2，已自审修订）**: `@src_v2/docs/stage_0_redesign.md`
**新代码位置**: `src_v2/`（与 `src/` 平级，旧目录不动）
**路线**: A2-a (Lark) + B2-y (unresolved 静默写入 contract) + C1-y (启发式 unmatched 走 stderr，不进 contract metadata)
**动手第一步**: `cp src/maude_parser/output/maude_contract.json src_v2/tests/maude_parser/baselines/stage_0_contract.before.json`



**实际在做什么**（probe 后版本）：用一组 regex 把若干 `.maude` 源文件切成 `Module / Op / Equation / Rule / View` 的内部 AST，再用一堆基于规则名子串的启发式把它们装配成 `MaudeContract` JSON。是 Stage 4a `NormalizationRegistry` 的离线前置依赖。

**Probe 命令**
```
cd src/
../venv/bin/python -m tests.walkthrough.stage_0_maude_contract
```
输入：`Maude/src/common/actor.maude`（58 行，纯 fmod）。
产物：`src/tmp_output/walkthrough/stage_0_contract.json`。

### Code map

| Symbol | Location | Role |
|---|---|---|
| `MaudeParserPipeline` | `src/maude_parser/pipeline.py:13-72` | 三步流水线 wrapper |
| `MaudeParserPipeline.main()` | `src/maude_parser/pipeline.py:75-110` | 唯一驱动；硬编码输入清单与输出路径 |
| `MaudeExtractor` | `src/maude_parser/extractors/maude_extractor.py:12-203` | regex AST 抽取，状态在 `self.modules / actor_types / actor_attributes` |
| `MaudeExtractor._parse_modules` | `src/maude_parser/extractors/maude_extractor.py:31-52` | 模块切分入口 |
| `MaudeExtractor._parse_subsorts` | `src/maude_parser/extractors/maude_extractor.py:71-79` | **F0-1 缺陷**: 单 parent regex |
| `MaudeExtractor._parse_ops` | `src/maude_parser/extractors/maude_extractor.py:81-106` | op 抽取，包含 `is_attribute` 的判定 (line 97) |
| `MaudeExtractor._parse_rules` | `src/maude_parser/extractors/maude_extractor.py:153-171` | `rl` / `crl` |
| `MaudeExtractor._extract_actor_info` | `src/maude_parser/extractors/maude_extractor.py:191-203` | 依赖 `coarity == 'ActorType'`，attribute 广播给所有已知 actor |
| `Module / Op / Equation / Rule / View` | `src/maude_parser/models/maude_ast.py:10-60` | 内部 AST |
| `JSONExporter.export_contract` | `src/maude_parser/exporters/json_exporter.py:26-54` | `MaudeContract` 装配总入口 |
| `JSONExporter._extract_actor_contracts` | `src/maude_parser/exporters/json_exporter.py:103-161` | actor → state/message interface（启发式） |
| `JSONExporter._extract_rule_contracts` | `src/maude_parser/exporters/json_exporter.py:163-207` | rule → guard/action slot（启发式） |
| `JSONExporter._infer_event_pattern` | `src/maude_parser/exporters/json_exporter.py:228-242` | 规则名子串 → 事件类型 |
| `JSONExporter._infer_state_access` | `src/maude_parser/exporters/json_exporter.py:244-258` | LHS/RHS 字符串包含 → reads/writes |
| `JSONExporter.export_to_json` | `src/maude_parser/exporters/json_exporter.py:334-340` | 写盘 |
| `pipeline_dto.PipelineConfig.contract_path` | `src/pipeline_dto.py:43` | Stage 4a 消费此 contract 的默认路径 |

### Friction notes

- **F0-1.** `_parse_subsorts` 只识别一个 parent，丢失链式 subsort。`@src/maude_parser/extractors/maude_extractor.py:71-79`. Probe 实证：`subsorts Address < AddrSet AddrList .` 只产出 1 条而非 2 条。**Edit surface**: 改 regex + 重新生成 `maude_contract.json`。
- **F0-2.** `is_attribute` 仅靠 `name.endswith(':_')` 判定，对 `to_:_` / `to_from_:_` 这类消息构造子误报为 True。`@src/maude_parser/extractors/maude_extractor.py:97`. 在 actor 非空（`dns.maude`）时会被 `_extract_actor_info` 广播分配给所有 actor。**Edit surface**: `_parse_ops` 的 `is_attr` 计算 + 也许加 `coarity != 'Msg'` 这种过滤；同时审 `_extract_actor_info` 的广播逻辑。
- **F0-3.** Actor 识别完全依赖 `coarity == 'ActorType'` 这个字符串硬匹配；attribute 归属是"广播给当前所有 actor"。`@src/maude_parser/extractors/maude_extractor.py:191-203`. 类型系统里真正的归属信息没被利用。**Edit surface**: `_extract_actor_info` 整段 + 或许下推到 `JSONExporter._extract_actor_contracts`。
- **F0-4.** 整条 exporter 链是规则名子串启发式（`'recv' in name`、`'cache' in rhs`、`'send' in rhs` …），下游 Phase 4 registry 把这些当 contract 信任源。命名约定一变就静默错配。`@src/maude_parser/exporters/json_exporter.py:209-279`. **Edit surface**: 这是一个面，要重设计的话基本要替换掉 `_infer_*` 全家。
- **F0-5.** `pipeline.py main()` 把要解析的文件清单和输出路径硬编码（`src/maude_parser/pipeline.py:84-110`），没有 CLI / config。**Edit surface**: 给 `main()` 加 argparse 或者把列表拎到一个 yaml。

---
