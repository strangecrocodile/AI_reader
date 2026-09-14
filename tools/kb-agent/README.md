# kb-agent · 教材入库 Agent（原型）

把**一整本书（.docx / .txt / .md）**自动处理成 **RAG 知识库 + 概念层**的独立原型工具。

> 定位：小组分工里“教材入库/拆书/建库/知识点抽取”这条线的验证原型。
> 已并入 AI_reader 仓库 `tools/kb-agent/`（main）。
>
> 与主产品的关系：主产品入库层现已支持 `.docx`/`.txt`/`.md`
> （`backend/app/parsing/`），并复用了本组件的 V2 知识点契约
> （`backend/app/services/concepts.py`）；本组件继续承担「整本书拆章落盘 +
> RAG 建库 + 概念图谱/思维导图预览」这条独立验证线，两者互不依赖。

## 新增能力（V2 起）

| 能力 | 说明 | 产物 |
|---|---|---|
| LangSmith 追踪 | 配 `LANGCHAIN_API_KEY` 即启用，run/ask/LLM 三层轨迹上报 | 平台轨迹 |
| 真书适配 | md 代码块过滤、一级标题成章、embedding 分批调用 | 见下 |
| V2 知识点抽取 | DeepSeek 结构化输出 `{concept, definition, prerequisites, example, anchors}`，规则兜底+清洗去重 | `concepts.json` |
| V2.5 概念图谱 | prerequisites→边、概念跨章合并去重、未解析前置单列 | `graph.json` |
| 图谱预览 | Cytoscape 单文件预览（数据内嵌，双击即开） | `graph-preview.html` |
| 思维导图 | 层级 Markdown 大纲 + markmap 渲染（可直接导入 markmap REPL / XMind） | `mindmap.md` / `mindmap.html` |
| **P4 讲义生成** | 概念层 + 原文锚点 → **前端契约讲义 JSON**（`heading/intro/paragraphs/knowledgePoints/outline`，知识点正文含可点击 `{t:'src'}` 锚点片段，按前置依赖拓扑排序） | `lessons/*.json` + `lessons/index.json` |

真书验证：《动手学深度学习》(d2l-zh, Apache-2.0) 6 章 → 7 份章节 docx / 79 检索块 / **73 知识点** / 图谱 **72 节点 72 边** / **6 章讲义（73 知识点，契约校验 0 错误）**。测试 **58 项**。

## 处理流水线（P0–P3 已实现）

```
整本书 .docx / .txt / .md（输入）
   │ P0 解析 + 字数统计         ✅ 读 Word 段落/样式；统计去空白字符/中文/英文词
   ▼
书本结构报告（书名｜章节｜每章字数｜总字数）
   │ P1 拆分 + 生成 Word        ✅ 章节识别（标题样式→文本模式兜底）；一章一份，
   │                             超大章按字数上限(默认 1 万字)切份；锚点清单
   ▼
章节 .docx + manifest.json（锚点 ↔ 段落）
   │ P2 知识库构建              ✅ 段落切块（超大段用 LangChain 递归切分兜底）→
   │                             向量化 → **BM25+向量 RRF 混合检索**
   │                             （向量默认离线哈希，可配真实 embedding，见下）
   ▼
RAG 知识库（JSON 持久化）→ 余弦检索
   │ P3 Agent 编排              ✅ LangChain @tool 声明工具：分析→拆书→建库→问答
   ▼
字数报告 / 章节 docx / manifest / kb.json / 检索问答（带锚点）
   │ V2  → concepts.json（知识点层）
   ▼
   │ V2.5 → graph.json → 图谱/思维导图预览
```

## 目录结构

```
kb-agent/
├── src/kb_agent/
│   ├── textstats.py   # 字数统计（口径统一）✅
│   ├── parse.py       # docx/txt/md → 段落行（文本+样式+层级）✅
│   ├── split.py       # 章节识别 + 拆书 + manifest ✅
│   ├── build_kb.py    # 切块 + 向量 + BM25/RRF 混合检索 ✅
│   ├── embeddings.py  # 嵌入工厂：API/本地语义模型 → 哈希回退 ✅
│   ├── extract.py     # V2 知识点抽取（LLM 优先，规则兜底 + 重试）✅
│   ├── graph.py       # V2.5 概念图谱数据（prerequisites→边）✅
│   ├── lesson.py      # P4 讲义生成（前端契约 JSON + 契约校验）✅
│   ├── langsmith_trace.py / llm_chat.py / config_env.py  # 追踪 / DeepSeek / .env
│   └── agent.py       # Agent 编排（run/ask/extract/graph/lessons + LangChain 工具）✅
├── scripts/
│   ├── make_sample_book.py       # 生成原创样例教材（版权安全）
│   ├── make_graph_preview.py     # 图谱预览 HTML
│   └── make_mindmap_preview.py   # 思维导图（markmap）预览
├── tests/             # pytest（58 项）
├── data/              # 运行期产物（不入库）
└── requirements.txt
```

## 运行方式（PowerShell）

```powershell
cd tools\kb-agent          # 从仓库根目录进入本组件
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 生成原创样例教材（可选）
.venv\Scripts\python.exe scripts\make_sample_book.py

# 全流程演示：分析 → 拆书 → 建库 → 问答 →（可选）知识点/图谱/讲义
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe -m kb_agent.agent data/source/sample_book.docx `
    --workdir data/out --query "什么是导数？" --extract --graph --lessons

# 测试
.venv\Scripts\python.exe -m pytest
```

## 换真实教材 / 真实模型（两处替换点，代码无需大改）

1. **换书**：把开源授权/有版权的整本 .docx 放到 `data/source/`，把上面的
   `sample_book.docx` 换成你的文件名即可（每份拆出的章节 docx 在 `data/out/chapters/`）。
2. **换向量模型（检索质量核心）**：问答检索已是 **BM25+向量 RRF 混合**
   （缺省哈希向量保证离线可用）。要启用真实语义向量，注入环境变量即可
   （建库与查询必须同一配置，模型失效会自动回退哈希，不会崩）：
   - OpenAI 兼容 API（如硅基流动 BGE-M3）：
     `EMBED_BASE_URL=https://api.siliconflow.cn/v1`、`EMBED_API_KEY=…`、`EMBED_MODEL=BAAI/bge-m3`；
   - 或本地模型：装 `sentence-transformers`，只设 `EMBED_MODEL=BAAI/bge-m3`。
3. **问答模型**：`agent.KBAgent(llm=callable)` 传入“用检索原文生成回答”的回调
   （OpenAI 兼容网关 / DeepSeek 均可），`ask()` 即返回生成式答案 + 锚点。

## 开发守则（沿用 AI_reader 仓库 AGENTS.md）

1. 每次改动完成后，必须创建对应 git commit，便于追踪与回滚；
2. 每次改动后必须编写或更新相关测试，交付前确保全部通过；
3. 每一步改动先向用户展示说明，用户看懂确认后再提交。
