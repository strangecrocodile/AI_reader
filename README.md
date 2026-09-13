# AI讲师 · 教材驱动的自主学习系统

导入教材 → 生成学习路径 → 章节学习 → AI 讲解与溯源问答。
回答以指定教材为边界，每条回答都能回到原文核对，而不是脱离教材的通用聊天。

## 目录结构

```
AI_reader/
├── docs/              # 赛题要求、产品设计、后端设计、下一阶段开发文档
├── frontend/          # React 19 + Vite 8 前端（主页 / 学习页 / 知识地图）
├── backend/           # FastAPI 后端（PDF/Word/文本解析 · RAG 检索 · 溯源问答 · 知识图谱）
└── tools/kb-agent/    # 教材入库 Agent 原型（.docx → 章节 Word + RAG 知识库，独立组件）
```

> `tools/kb-agent` 是一条独立验证线（Word 教材拆书建库），有自己的依赖和虚拟环境，
> 与 `backend` 互不依赖。只想跑主产品（前端 + 后端）的话，可以完全跳过它。

## 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.10 及以上（开发使用 3.13） | 运行 `backend` 与 `tools/kb-agent` |
| Node.js | `^20.19` 或 `>=22.12`（开发使用 24） | 运行 `frontend`，下限由 Vite 8 决定 |
| npm | 随 Node.js 安装 | 安装前端依赖 |

不需要 GPU。**不配置任何模型 Key 也能跑通完整演示**（后端自动规则回退，前端可用内置演示数据）。

---

## 一、首次安装（拿到源代码后只做一次）

### 1. 后端（主产品，必需）

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

生成一本**团队原创**的示例教材。`backend/data/` 不纳入 Git，**首次必须执行这一步**（之后也可在页面上传自己的 PDF）：

```powershell
.venv\Scripts\python.exe scripts\make_demo_pdf.py
```

配置大模型（可选，推荐）。复制 `backend\.env.example` 为 `backend\.env`，填入 DeepSeek 的 Key：

```
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的key
LLM_MODEL=deepseek-chat
```

> 不填 `LLM_API_KEY` 时后端使用规则 mock 回退，完整链路照样能演示。

### 2. 前端（主产品，必需）

```powershell
cd frontend
npm install          # 或 npm ci，严格按 package-lock.json 还原
```

让前端连接本地后端：复制 `frontend\.env.example` 为 `frontend\.env`（默认已指向 `http://localhost:8000`）。

> 不创建 `frontend\.env` 时，前端使用内置演示数据，页面能打开，但无法上传真实 PDF、也无法读后端数据。

### 3. 教材入库 Agent 原型（可选，独立组件）

只在你需要验证「整本 .docx → 拆章 → 建 RAG 知识库」这条链路时安装：

```powershell
cd tools\kb-agent
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

生成原创样例教材（`tools/kb-agent/data/` 不纳入 Git，首次需执行）：

```powershell
.venv\Scripts\python.exe scripts\make_sample_book.py
```

配置模型（可选）：复制 `tools\kb-agent\.env.example` 为 `tools\kb-agent\.env`，按注释填写
`LLM_API_KEY`（问答用 DeepSeek）与 `EMBED_*`（语义检索用；全不填则用 BM25 + 哈希向量离线兜底）。

---

## 二、每次调试启动（日常开发）

主产品需要**两个终端**，一个常驻后端、一个常驻前端。

### 终端 1 · 启动后端（端口 8000）

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

- 接口文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health（返回的 `llm` 字段为 `cloud` 或 `mock`，可确认模型是否接上）

### 终端 2 · 启动前端（端口 3000）

```powershell
cd frontend
npm run dev
```

浏览器会自动打开 http://localhost:3000（已在 `frontend/vite.config.mjs` 中设置 `port: 3000`、`open: true`）。

> 改后端代码由 `--reload` 自动重启，改前端代码由 Vite 热更新自动刷新，**两个终端都不需要重启**。

macOS / Linux 用户把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python` 即可。

### 运行教材入库 Agent（按需，一次性执行，无需常驻）

```powershell
cd tools\kb-agent
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe -m kb_agent.agent data\source\sample_book.docx --workdir data\out --query "什么是导数？"
```

它会依次完成「字数分析 → 拆书 → 建库 → 检索问答」，产物在 `data\out\`（章节 docx、`manifest.json`、`kb.json`）。
换真实教材时，把 `.docx` 放进 `data\source\` 并替换上面的文件路径即可。

---

## 三、运行测试

提交改动前，请确保相关套件全部通过。测试均不依赖模型 Key，也不访问外网。

```powershell
# 后端：115 项
cd backend
.venv\Scripts\python.exe -m pytest

# 前端：69 项
cd frontend
npm test

# kb-agent：需先按「首次安装 · 第 3 步」装好它自己的依赖
cd tools\kb-agent
.venv\Scripts\python.exe -m pytest
```

---

## 四、常用命令速查

| 目的 | 命令（在对应目录下执行） |
|---|---|
| 启动后端（热重载） | `.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000` |
| 换端口启动后端 | `.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001` |
| 重新生成示例教材（PDF） | `.venv\Scripts\python.exe scripts\make_demo_pdf.py` |
| 跑后端测试 | `.venv\Scripts\python.exe -m pytest` |
| 启动前端开发服务器 | `npm run dev` |
| 跑前端测试 | `npm test` |
| 前端测试监听模式 | `npm run test:watch` |
| 构建前端产物 | `npm run build` |
| 生成样例教材（Word） | `.venv\Scripts\python.exe scripts\make_sample_book.py`（在 `tools\kb-agent`） |
| 跑 kb-agent 全流程 | `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m kb_agent.agent <书.docx> --workdir data\out` |

---

## 五、体验完整链路

1. 打开 http://localhost:3000 —— 主页展示从后端加载的教材与学习路径；
2. 点击「更换教材」→「上传」，导入 **PDF / Word(.docx) / 纯文本(.txt/.md)** 教材
   （PDF 带目录书签、Word 带标题样式时章节识别最准；`.doc` 请先另存为 `.docx`）；
3. 进入章节 —— 左栏教材原文、右栏 AI 讲解。**拖选一段原文，选区旁会浮出「问 AI」气泡**，
   点开就是可拖动的追问浮层，可连续追问；右栏「追问线程」列表能切换回看、定位回原文。
   回答**逐字流式返回**，附带「教材依据」可一键回跳原文；本章没讲到的内容会自动扩展到全书检索，
   跨章依据会标出章节名并可跳过去核对。
   右栏顶部是**掌握度面板**：读过的段落、提问次数实时计入，面板会列出每一项的权重与得分，
   也能手动「标记本章学完」；
4. 进入「知识地图」—— 查看跨章节沉淀的知识点卡片、**前置依赖**（实线带箭头）与**学习顺序**（虚线），
   教材里没有出现过的前置概念会单独列出；点击节点可回到对应章节原文核对。

---

## 六、常见问题

**页面能打开，但列表是示例数据、无法上传 PDF？**
`frontend\.env` 未创建或 `VITE_API_BASE_URL` 为空，前端处于内置演示数据模式。按「首次安装 · 第 2 步」创建 `.env`，再重启 `npm run dev`。

**讲解和回答偏模板化？**
`backend\.env` 没配 `LLM_API_KEY`，后端在用规则回退。填入 DeepSeek Key 后重启后端即切换为真实推理（`/api/health` 的 `llm` 会变成 `cloud`）。

**为什么回答的依据来自其他章节？**
本章检索覆盖率不足（低于 0.22）时，后端会自动把检索范围扩展到全书——教材里讲过的内容就不会答“没依据”。
界面会提示“本章依据不足，已扩展到全书检索”，跨章依据按钮带章节名，点击即跳到那一章核对原文。

**刷新页面后追问记录还在吗？**
在。每条划词追问都是一条线程（`threads` / `thread_messages`），回答与溯源信息一起持久化；
右栏「追问线程」列表可随时切回，并定位到它对应的那段原文。演示模式（未连后端）把线程存在浏览器本地。

**端口被占用（8000 / 3000）？**
后端换端口启动（如 `--port 8001`），并把 `frontend\.env` 的 `VITE_API_BASE_URL` 同步改成对应地址；前端端口可在 `frontend/vite.config.mjs` 调整。

**知识地图为空或提示不可用？**
知识地图由章节原文抽取出的知识点聚合而来，需要先有一次教材成功入库。确认已执行 `scripts\make_demo_pdf.py`，或先在主页上传一本教材。

**上传 `.doc` 或扫描件 PDF 报错？**
`.doc`（旧版二进制 Word）不支持，请用 Word 另存为 `.docx`；扫描件 PDF 没有文本层，属于产品范围之外（见 `docs\产品设计文档.md` 第 6 节）。

**掌握度是怎么算的？**
由真实学习事件算出：覆盖度（读过的正文段落占比，权重 50）+ 互动度（不同提问数封顶 5，权重 25）
+ 自测正确率（权重 25，无自测记录时按比例并入前两项）。乱报锚点、重复提问都不计分，
掌握度只增不减；学习页会列出每一项的得分。公式见 `docs\后端设计文档.md` 第 7 节。

**`tools\kb-agent` 报 `ModuleNotFoundError: kb_agent`？**
启动前需要设置 `$env:PYTHONPATH = 'src'`（测试不用，`conftest.py` 已自动处理）。

**本机装了 conda，影响 Python 环境？**
可先执行 `conda deactivate`。本仓库所有命令都直接调用 `.venv\Scripts\python.exe` 全路径，**不依赖事先激活虚拟环境**，conda 是否激活都不影响。

---

## 七、版权与合规

- 演示材料由脚本生成、内容为**团队原创**，可安全用于公开演示：
  `backend/data/demo_textbook.pdf`（来自 `backend/scripts/make_demo_pdf.py`）、
  `tools/kb-agent/data/source/sample_book.docx`（来自 `tools/kb-agent/scripts/make_sample_book.py`）。
- 接入真实教材时，须使用具有合法使用权的 PDF / Word 文档。
- 使用的开源组件与许可证清单见 `docs/后端设计文档.md` 第 2、7 节（FastAPI、Uvicorn、PyMuPDF、pydantic、httpx、python-dotenv、pytest 等）。

详细设计见 `docs/产品设计文档.md`、`docs/后端设计文档.md`、`docs/下一阶段开发文档.md`
与 `tools/kb-agent/README.md`。
