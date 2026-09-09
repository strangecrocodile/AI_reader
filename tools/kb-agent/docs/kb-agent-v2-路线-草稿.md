# kb-agent v2 路线（草稿，待小组评审）

> 状态：**草稿，尚未评审、未提交 git**。
> 定位转变：kb-agent 从“Word 拆书建库的独立原型”，演进为
> **“统一入库 + 知识抽取层”**——docx/PDF 都能收、产出统一锚点与知识点数据，
> 成为“读教材 → 提炼知识点 → 讲义/题目 → 回写知识库”闭环的入库底座。
>
> 依据：小组全局方案（RAG 为底座、图谱/wiki 为展示、一个月四步走）+ 开源调研
> （SmartKB-RAG、legal_rag、Docling、novel-rag、react-pdf-highlighter-plus 等）。

---

## 0. 一句话结论

图谱不是另起炉灶，而是从“已入库的段落+锚点”里长出知识点层；
kb-agent 的产出（manifest）应扩展为 **段落层 + 概念层 + 统一锚点** 三件套。

## 1. 待小组先拍板的 4 个决策点（决定 v2 方向）

| # | 决策点 | 选项 | 影响 |
|---|--------|------|------|
| 1 | 主线教材格式 | Word（现有原型）/ PDF（队友后端/阅读器） | 决定解析升级投入 |
| 2 | 锚点坐标模型 | 统一为 `(book_id, source_type, page?, para_index, char_span)` | 决定高亮/引用能否跨 docx/PDF 共用 |
| 3 | 向量/检索 | 哈希(临时) → bge-m3 本地或 API；BM25+向量 RRF 混合 | 决定检索质量与成本 |
| 4 | 编排框架 | LangChain（当前）与 LlamaIndex 二选一主用 | 避免两套深挖 |

> 版本历史问题已明确交给组员处理；本仓库为本地草稿，**不推 GitHub、不碰 AI_reader**。

## 2. v2 分阶段（每阶段：目标 / 改动 / 验收）

### V2.0 数据契约先行（本周可做，与 UI 无关）
- 统一锚点 JSON 结构：`{book_id, source_type: docx|pdf, page?, para_index, char_span?}`
- manifest 升级为 v2：`{book, chapters[], paragraphs[{anchor,text}], concepts[]}`
  （concepts 先留空结构，V2.3 填充）
- 验收：样例书跑通，v1 数据可无损迁移到 v2。

### V2.1 解析升级（吃结构，不吃猜测）
- 尝试 Docling / unstructured 把 docx（以及队友侧 PDF）归一为带结构的 markdown/JSON；
  章节识别基于结构而非“样式+正则兜底”。
- 验收：乱样式文档的章节识别率提升（准备 1 份“故意乱排版”的 fixture 对比）。
- 依赖：docling（如体积过大则降级为保留现有解析 + 增加校验告警）。

### V2.2 检索升级（补“哈希向量语义弱”）
- 向量：HashEmbedder → bge-m3（本地 sentence-transformers 或 SiliconFlow 等 API，走 .env）；
- 混合：BM25 + 向量，RRF 融合（参考 novel-rag / SmartKB-RAG），可插拔 rerank；
- 验收：语义近义查询（如“切线斜率”↔“导数几何意义”）能从第 2 章召回（当前哈希会漏）。
- 依赖：若走 API 需确认 key；本地 bge-m3 需 ~1–2GB 模型与时间。

### V2.3 知识点抽取与概念层（产品核心）
- 在 chunk 之上做 LLM 结构化抽取，输出 JSON：
  `{concept, definition, prerequisite[], example?, anchor[]}`；
- 无 key/离线时提供规则回退（抽取章节内术语/定义句），保证可演示；
- 讲义 = 按前置依赖排序渲染知识点；题目 = 知识点模板 + LLM 变体（后置）。
- 验收：样例书产出 ≥N 个概念，每个概念能回链 ≥1 个锚点；讲义可按依赖排序。
- 依赖：LLM（对齐全局方案“LangChain/LlamaIndex 选一”，选型见决策 4）。

### V2.4 数据契约与回写/流式预留
- 问答/讲义 JSON 预留字段：`thread_id / mastery / cards / notes`；
- 接口形状对齐队友后端 FastAPI（SSE/流式），kb-agent 只产数据不产 UI。
- 验收：契约文档化；样例 JSON 可用作前端 mock。

### V2.5 与队友后端/前端对接（由小组统一排期）
- docx/PDF 两套入库产物在“统一锚点”下合并；
- 阅读器高亮/气泡（react-pdf-highlighter-plus 起步）消费统一锚点；
- 图谱页（Cytoscape.js）直接渲染 V2.3 的 concepts/关系，节点回链教材页/卡片/笔记。

## 3. 对齐小组“一个月四步走”的落点

| 小组周计划 | kb-agent 贡献 |
|---|---|
| W1 数据模型 + PDF 能选中高亮 | V2.0 统一锚点/契约（先定，避免返工） |
| W2 AI 气泡/追问/流式 | V2.4 接口契约与流式预留 |
| W3 RAG 索引 + 知识点抽取 + 讲义/题目 | V2.2 检索升级 + V2.3 抽取与讲义数据 |
| W4 图谱页/卡片/笔记 | V2.3 concepts → 图谱数据供给 |

## 4. 明确不做（本期范围外）

- 不做 UI/图谱页面本身（小组前端认领）；
- 不做完整 LLM wiki（RAG 底座优先）；
- 不推 GitHub、不改 AI_reader 版本历史（组员处理）。
