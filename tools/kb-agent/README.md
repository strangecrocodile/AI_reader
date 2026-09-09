# kb-agent · 教材入库 Agent（原型）

把**一整本书的 Word 文档（.docx）**自动处理成 **RAG 知识库**的独立原型工具。

> 定位：小组分工里“教材入库/拆书/建库”这条线的验证，放 D 盘独立目录，
> 不进入 AI_reader/backend（那是后端同学的代码，只收 PDF；本原型验证 Word 教材入库链路）。

## 处理流水线（P0–P3 已实现）

```
整本书 .docx（输入）
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
```

## 目录结构

```
kb-agent/
├── src/kb_agent/
│   ├── textstats.py   # 字数统计（口径统一）✅
│   ├── parse.py       # docx → 段落行（文本+样式+层级）✅
│   ├── split.py       # 章节识别 + 拆书 + manifest ✅
│   ├── build_kb.py    # 切块 + 向量 + BM25/RRF 混合检索 ✅
│   ├── embeddings.py  # 嵌入工厂：API/本地语义模型 → 哈希回退 ✅
│   └── agent.py       # Agent 编排（run/ask/summarize + LangChain 工具）✅
├── scripts/make_sample_book.py  # 生成原创样例教材（版权安全）
├── tests/             # pytest（22 项）
├── data/              # 运行期产物（不入库）
└── requirements.txt
```

## 运行方式（PowerShell）

```powershell
cd D:\kb-agent
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 生成原创样例教材（可选）
.venv\Scripts\python.exe scripts\make_sample_book.py

# 全流程演示：分析 → 拆书 → 建库 → 问答
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe -m kb_agent.agent data/source/sample_book.docx `
    --workdir data/out --query "什么是导数？"

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
