# RFC 协议形式化全流程 Pipeline

将 DNS 相关 RFC 文档自动转化为 Maude 重写逻辑的形式化代码，用于协议的形式化验证与攻击发现。

## 整体架构

```
RFC 文档 (RFC ID)
  │
  ▼  Phase 1: rfc_processor/orchestrator.py
NetworkX 有向图 (节点=RFC/Section, 边=引用关系) + Section Embeddings
  │
  ▼  Phase 2: rfc_processor/rag_router.py
ContextPack (seed + local_structure + references + semantic_expansion)
  │
  ▼  Phase 3: IR_extractor/ir_pipeline.py  [LLM]
Semantic IR (ECA rules: event-condition-action)
  │
  ▼  Phase 4a: maude_generator/normalizer.py  [Rule-based + LLM-assisted]
  ▼  Phase 4b: maude_generator/validator.py
  ▼  Phase 4c: maude_generator/generator.py
Maude 源代码 (.maude)
  │
  ▼  Phase 5: main.py / FormalExecutor        [TODO]
  ▼  Phase 6: main.py / ClosedLoopRepair      [TODO]
形式化验证结果 → 闭环修正
```

## 运行方式

```bash
# 从 src/ 目录运行
cd src/
python main.py
```

需要先配置 LLM API key（见 `llm/config.yaml` 中的 `api_key_env` 字段对应的环境变量）。

## 目录结构

```
src/
├── main.py                  # 全流程编排器 (FormalizationPipeline)
│
├── llm/                     # LLM 客户端层
│   ├── __init__.py
│   ├── config.yaml          #   LLM provider 配置 (API key 通过环境变量注入)
│   ├── llm_client.py        #   BaseLLMClient + OpenAICompatibleClient + GeminiClient
│   └── factory.py           #   create_llm_client() 工厂函数
│
├── rfc_processor/           # Phase 1 & 2: RFC 图谱构建 + ContextPack 组装
│   ├── __init__.py
│   ├── rfc_parser.py        #   RFCGraphBuilder: XML/TXT → NetworkX 有向图
│   ├── orchestrator.py      #   RFCGraphOrchestrator: BFS 递归构建 + embedding 索引
│   ├── graph_knowledge_base.py  # GraphKnowledgeBase: 图查询 DAO
│   ├── rag_router.py        #   GraphRAGRouter + SemanticRanker → ContextPack
│   ├── embedding.py         #   SectionEmbeddingIndexer: 离线 embedding 计算
│   └── embedding_store.py   #   NumpyEmbeddingStore: .npy + .json 向量存储
│
├── IR_extractor/            # Phase 3: ECA-style IR 抽取
│   ├── __init__.py
│   ├── ir_pipeline.py       #   IRExtractionPipeline: prompt → LLM → JSON → 校验
│   └── semantic_ir.json     #   IR schema 定义 (ECA 格式)
│
├── maude_generator/         # Phase 4: 归一化 + 校验 + Maude 代码生成
│   ├── __init__.py
│   ├── config/              #   YAML 别名映射 (modality, role, event, action)
│   ├── registry.py          #   NormalizationRegistry: 6 个子注册表
│   ├── normalizer.py        #   RuleBasedNormalizer + LLMAssistedNormalizer
│   ├── validator.py         #   MaudeValidator: 4 层校验
│   ├── generator.py         #   MaudeGenerator: IR → Maude 重写规则
│   └── dto.py               #   GenerationResult 数据对象
│
├── maude_parser/            # Maude 源码解析 (已有模型 → contract)
│   ├── __init__.py
│   ├── pipeline.py          #   MaudeParserPipeline: 解析 → 提取 → 导出
│   ├── extractors/          #   Maude 语法提取器
│   ├── exporters/           #   JSON / DOT 导出器
│   ├── models/              #   AST 数据模型
│   ├── output/              #   maude_contract.json (被 Phase 4 Registry 消费)
│   └── visualization/       #   可视化产物
│
├── tests/                   # 测试代码
│   ├── test_ir_extraction_demo.py
│   └── test_rfc_processor/
│       ├── test_visualize.py
│       ├── test_1hop_recursive.py
│       ├── test_recursive_depth.py
│       └── test_embedding.py
│
└── tools/                   # 独立工具脚本
    ├── analyze_rfc_deps.py      # RFC 依赖链分析 + 可视化
    ├── visualize.py             # 图谱树状可视化
    └── rfc_processor_demo.py    # Phase 1&2 独立 demo
```

## 模块依赖关系

```
                 ┌──────────────┐
                 │   main.py    │  ← 全流程编排
                 └──────┬───────┘
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌─────────────┐ ┌──────────────┐
│rfc_processor/│ │IR_extractor/│ │maude_generator│
│  Phase 1&2   │ │  Phase 3    │ │  Phase 4      │
└──────────────┘ └──────┬──────┘ └───────┬───────┘
                        │                │
                        ▼                ▼ (通过 JSON 文件)
                   ┌─────────┐   ┌─────────────┐
                   │  llm/   │   │maude_parser/ │
                   └─────────┘   │  (contract)  │
                                 └─────────────┘
```

- **main.py** 依赖所有模块，编排 Phase 1→6
- **IR_extractor/** 依赖 `llm/`（LLM 调用）
- **maude_generator/** 依赖 `maude_parser/output/maude_contract.json`（文件级依赖，非 import）
- **rfc_processor/** 无跨模块代码依赖（独立运行）

## 核心数据格式

### Semantic IR (Phase 3 输出 → Phase 4 输入)

```json
{
  "semantic_rules": [
    {
      "id": "server-listen-port-853",
      "modality": "MUST",
      "actor": { "name": "DNS server", "type": "role" },
      "event": { "kind": "recv", "expr": "receives a TLS connection request" },
      "conditions": [
        { "kind": "guard", "expr": "connection is on port 853" }
      ],
      "actions": [
        { "kind": "reply", "expr": "accept the TLS connection" }
      ],
      "provenance": {
        "document": "RFC7858",
        "section": "Section 3.1",
        "anchor": "...",
        "source_text": "..."
      }
    }
  ]
}
```

### ContextPack (Phase 2 输出 → Phase 3 输入)

```json
{
  "seed": { "id": "...", "text": "...", "title": "..." },
  "local_structure": {
    "ancestors": [],
    "descendants": []
  },
  "references": {
    "normative": { "section_level": [], "document_level": [] },
    "informative": { "section_level": [], "document_level": [] }
  },
  "semantic_expansion": [],
  "trace": []
}
```

## 实现状态

| 阶段 | 状态 | 关键类 |
|------|------|--------|
| Phase 1: RFC 图谱构建 | ✅ | `RFCGraphOrchestrator` |
| Phase 2: ContextPack 组装 | ✅ | `GraphRAGRouter`, `SemanticRanker` |
| Phase 3: IR 抽取 | ✅ | `IRExtractionPipeline` |
| Phase 4: Maude 代码生成 | ✅ | `RuleBasedNormalizer`, `MaudeValidator`, `MaudeGenerator` |
| Phase 5: 形式化执行 | ⬜ TODO | `FormalExecutor` (placeholder) |
| Phase 6: 闭环修正 | ⬜ TODO | `ClosedLoopRepairController` (placeholder) |

## 上游依赖

本项目基于以下已有工作：

- **Maude DNS 形式化模型** (`Maude/` 目录) — 来自 SIGCOMM 论文 *"A Formal Framework for End-to-End DNS Resolution"*，提供了 DNS actor、消息结构、重写规则的参考实现
- **Testbed** (`Testbed/` 目录) — Go 语言实现的 Docker 化 DNS 实验环境
