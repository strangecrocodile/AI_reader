# 方法方案：教材入库 Agent（LangChain + RAG 知识库）

> 版本：v1（待评审）
> 目标项目：AI_reader（AI讲师 · 教材驱动的自主学习系统）
> 本文是「方法」，代码尚未开始。评审确认后再按本文 Phase 0→4 逐步落地，每个改动先展示再提交。

---

## 0. 目标（大白话）

造一个 **“教材入库 Agent”**：把一整本书的 Word 文档（.docx）丢给它，它能自动完成三件事：

1. **自己数清楚字数**：全书总字数、每个章节多少字；
2. **自己拆书**：一章生成一个独立的 Word 文档；某章太大（超过字数上限）就按字数再切成多份；
3. **自己建知识库**：把这些章节 Word 文档喂给 RAG 知识库（切块 → 向量化 → 检索），
   以后 AI讲师 的讲解与问答都从知识库取原文依据，替代现在前端 `books.js` 里的假数据。

## 1. 已确认的决策（评审拍板结果）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 原始书输入格式 | **整本书 Word（.docx）** |
| 2 | 拆分策略 | **一章一份 .docx；超大章再按字数上限切**（上限默认 10000 字，可配） |
| 3 | 代码位置 | **AI_reader 仓库内新增 `backend/`**（Python 工程，与前端同仓） |
| 4 | 大模型 | **用现有可用的 OpenAI 兼容网关/DeepSeek key**（如本机 OpenMAIC 网关），key 放 `.env` 不入库 |

## 2. 名词解释（先看懂再往下）

- **Agent**：不是普通的“一问一答”，而是能自己调用工具、看结果、决定下一步的程序。这里用 LangChain 把工具挂给它，它按“分析→拆→建库”自动干活。
- **RAG（检索增强生成）**：每次提问前，先从知识库里捞出与问题最相关的几段原文，连问题一起交给大模型，让它“看着教材说话”——答案可溯源、不易瞎编。
- **切块（chunking）**：长文本不能整段喂给模型，按段落切成 500–1000 字的小块，块间留约 10% 重叠，避免语义被切断。
- **向量化（embedding）**：把一段文字变成一串数字（向量），意思相近的文字，数字也相近。
- **向量库（vector store）**：存“文字向量”的数据库，按相似度召回原文。起步用 Chroma，免部署。
- **锚点（source id）**：给原文每个段落一个稳定编号（如 `calc7-ch2-p3`），前端点击“教材依据 #xx”就能跳回原文高亮。与前端 `SegmentText.jsx` 的机制对齐。

## 3. 总体流水线

```
整本书 .docx（输入）
   │ P0 解析 + 字数统计        （读 Word → 识别章节 → 统计字数）
   ▼
书本结构报告（书名｜章节｜每章字数｜总字数）
   │ P1 拆分 + 生成 Word       （一章一份 .docx，超大章按字数切；写锚点清单）
   ▼
章节 .docx 文件集 + manifest.json（锚点↔段落映射）
   │ P2 知识库构建             （LangChain 加载 .docx → 切块 → 向量化 → 入 Chroma）
   ▼
RAG 向量知识库
   │ P3 Agent 编排 + 问答      （提问 → 召回原文 → 大模型回答 → 带教材依据返回）
   ▼
AI讲师 讲解 / 溯源问答（对接现有前端 api.js 契约）
```

## 4. 各阶段详细设计

### P0 解析与字数统计
- **输入**：整本书 .docx。
- **做法**：用 `python-docx` 逐段读取，保留段落样式（Heading 1/2…）与文本。
- **章节识别（按优先级）**：
  1. Word 原生“标题”样式（Heading 1）→ 视为章标题；
  2. 无标题样式时，匹配常见章标题文本模式（`第X章`、`Chapter X`、`X.` 数字小节等）；
  3. 都失败则默认整本为“单章”，交给 Agent 的 LLM 判断自然断点（提示用户确认）。
- **字数口径（写清楚，避免扯皮）**：
  - 中文字数 = 正文中的中文字符（CJK）计数；
  - 总字符 = 去除空白后的全部字符；
  - 英文按词数统计；三者都在报告里给出。
- **输出**：书本结构报告（书名/章节列表/每章字数/总字数/章节数）。报告同时存入 `manifest.json` 供后续检索元数据使用。

### P1 拆分与生成 Word
- **策略**：一章一份；若某章字符数 > `SPLIT_CHAR_LIMIT`（默认 10000，可配），按字符数切成多份，文件名带序号。
- **命名规则**：`{book_id}_ch{NN}.docx`；切分后 `_ch{NN}_part{k}.docx`。
- **每份 .docx 的结构**：首页元信息表（书名/版本/章节号/页码范围/字数）→ 章节标题 → 正文段落（保留原段落边界）。
- **锚点**：每个正文段落分配稳定 id（`{book_id}-{chapter_id}-p{序号}`），段落清单写入 `manifest.json`。**锚点只进 manifest，不污染正文文本**，否则会干扰后续检索。
- **输出**：`data/chapters/` 下一批章节 .docx + `data/manifest.json`。

### P2 知识库构建（RAG 核心）
- **加载**：LangChain `Docx2txtLoader`（或 `DirectoryLoader` 批量）读取章节 .docx。
- **切块**：`RecursiveCharacterTextSplitter`，chunk_size ≈ 800 字符、overlap ≈ 100（可调），优先按段落边界切。
- **向量化**：首选开源本地 embedding（bge-m3 / m3e），备选 API embedding；模型与 key 放 `.env`。
- **入库**：Chroma（本地目录持久化）。**每个切块写入 metadata**：`{book_id, chapter_id, docx_file, para_range, source_ids[]}`——这样检索命中后能精确返回锚点，驱动前端“教材依据”跳转。
- **输出**：本地向量库目录 + 构建日志（每个文档多少块、入库总数）。

### P3 Agent 编排 + 问答
- **Agent 工具集**（LangChain Tool / 自封装函数）：
  - `analyze_book(docx)`：P0 字数统计；
  - `split_to_docs(docx, limit)`：P1 拆书；
  - `build_kb(dir)`：P2 建库；
  - `ask(question, top_k)`：检索 + 生成，返回 `{text, sources:[anchor...]}`。
- **流程**：Agent 拿到“待处理书”→ 依次调用 `analyze_book → split_to_docs → build_kb`，关键节点向用户汇报字数与拆分结果，确认后再继续。
- **问答兜底**：检索不到相关原文时，回答明确返回“教材中未找到直接依据”，不编造（对齐产品设计文档 4.4）。
- **输出契约**：与前端 `frontend/src/services/api.js` 的既有注释契约一致：
  - `POST /api/ask` 入参 `{question, selectedText?, bookId, chapterId}`；
  - 返回 `{text, sources: string[]}`（sources 即锚点 id 列表，前端可直接渲染“教材依据 #xx”）。

## 5. 工程目录结构（backend/，与前端同仓）

```
AI_reader/backend/
├── pyproject.toml          # Python 依赖与工程信息
├── .env.example            # 环境变量样例（真实 .env 不入库）
├── kb_agent/
│   ├── __init__.py
│   ├── parse.py            # P0：docx 解析 + 字数统计
│   ├── split.py            # P1：章节识别 + 拆 .docx + 锚点清单
│   ├── build_kb.py         # P2：docx → 切块 → 向量库
│   ├── qa.py               # P3：检索问答（带锚点）
│   ├── tools.py            # Agent 工具定义
│   └── agent.py            # LangChain Agent 编排（主入口）
├── data/                   # 运行期数据（不入库：.gitignore）
│   ├── source/             #   原始整本书 .docx
│   ├── chapters/           #   拆出的章节 .docx
│   ├── manifest.json       #   锚点映射
│   └── chroma/             #   向量库
└── tests/                  # pytest（守则：先测后交）
    ├── fixtures/           #   开源授权的小样章书
    ├── test_parse.py
    ├── test_split.py
    └── test_build_kb.py
```

## 6. 环境配置（LLM 接入）

- 变量（均走 OpenAI 兼容协议）：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`EMBED_MODEL`。
- 真实值写 `backend/.env`；仓库 `.gitignore` 已忽略 `.env*`（除 `.env.example`），**密钥永不进 commit**。
- 可选来源：本机 OpenMAIC 网关的 OpenAI 兼容端点，或 DeepSeek 官方 API；Phase 4 接线时再定具体 base_url 与模型名。

## 7. 与现有前端衔接

1. `manifest.json` 的锚点 id 规则与前端 `SegmentText.jsx`/`data/books.js` 的 `source-*` 约定同构，保证“教材依据”跳转可用；
2. 后端提供 `GET /api/books`、`GET /api/study/:bookId/:chapterId`、`POST /api/ask`，替换 `api.js` 里的 mock（前端零改动即可切换，`api.js` 注释已预留）；
3. 首次真实验证：选择一本开源授权、文字为主的书完整入库，用真数据替换 `books.js` 中对应演示位。

## 8. 测试与验收（遵守仓库 AGENTS.md 守则）

> 守则：每次改动完成必须创建 Git commit；每次改动必须编写/更新相关测试，交付前全部通过。

- **单元测试**：
  - `test_parse.py`：字数统计口径正确；章节识别（标题样式/文本模式/兜底）用例覆盖；
  - `test_split.py`：一章一份、超大章按上限切分、文件名与锚点编号正确；生成 .docx 可被 python-docx 重读且内容一致；
  - `test_build_kb.py`：小样章建库后，命中块 metadata（book/chapter/source_ids）正确；相似度查询能召回“该章节原文”。
- **集成验收（人工可复核）**：
  1. 输入一本小样章 .docx → 报告字数与手工统计一致；
  2. 产物 .docx 用 Word/WPS 打开正常，标题层级与原文完整；
  3. 建库后提问“这段在讲什么”→ 回答内容来自原文并带正确锚点；
  4. 前端切到后端数据后，“教材依据”可跳转高亮。
- 交付物：每阶段代码 + 测试全绿 + 展示改动明细 + 对应 commit。

## 9. 分阶段路线图（每步交付可见）

| Phase | 内容 | 交付物 |
|-------|------|--------|
| 0 | backend 工程骨架 + 依赖 + 小样章 fixture + P0 解析/统计 | `parse.py` + pytest 全绿；一页字数报告 |
| 1 | P1 章节识别 + 拆分 .docx + manifest | 章节 .docx 样例文件（可打开检查） |
| 2 | P2 docx → 向量库 + 检索测试 | 建库脚本 + 召回验证 |
| 3 | P3 Agent 编排（一个命令完成“分析→拆→建库”） | `agent.py` + 端到端演示 |
| 4 | 后端 API 接线前端 + 真实书完整入库验证 | AI讲师真数据版 demo |

## 10. 风险与边界（提前讲清）

1. **Word 样式差异**：来源 docx 若标题没套样式、章名五花八门，识别率下降——P0 用“样式 + 文本模式 + LLM 兜底”三级策略，并保留人工确认环节。
2. **公式/图片/表格**：.docx 中的公式对象与图片无法直接取文本，会作为“公式占位”跳过；表格按单元格文本扁平化。数学教材的公式呈现是后续专题，不阻塞文字为主的书。
3. **版权合规**（赛题硬性要求）：样章与正式入库书必须用**开源授权/团队有合法使用权的材料**，不得用盗版教材；《开源及第三方资源使用清单》后续补齐。
4. **扫描件/OCR**：不在本方案范围（产品设计文档已明确）。
