# AI讲师 · 教材驱动的自主学习系统

导入教材 → 生成学习路径 → 章节学习 → AI 讲解与溯源问答。
回答以指定教材为边界，每条回答都能回到原文核对，而不是脱离教材的通用聊天。

## 目录结构

```
AI_reader/
├── docs/              # 赛题要求、产品设计、后端设计、下一阶段开发文档
├── frontend/          # React 19 + Vite 8 前端（主页 / 学习页 / 知识地图）
├── backend/           # FastAPI 后端（PDF/Word/文本解析 · 扫描件 OCR · RAG 检索 · 溯源问答 · 知识图谱）
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

不需要 GPU，扫描件 OCR 也是纯 CPU 跑的。**不配置任何模型 Key 也能跑通完整演示**
（后端自动规则回退，前端可用内置演示数据）。

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

**可选：让扫描件 PDF 也能导入（OCR）。** 不装的话其它格式完全不受影响，只是上传扫描件时
后端会返回一条带安装指引的提示：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
```

这条依赖（`rapidocr` + `onnxruntime`）刻意**不放进 `requirements.txt`**：它有 100 MB 上下，
而「不装模型、不配 Key 就能跑通演示」是本项目的核心卖点，不该被一个可选功能拖累。
装好后模型随 wheel 一起到位，**首次识别也不联网**。识别是纯 CPU 的，一本 300 页的扫描教材
大约十几分钟，期间可以在页面上正常做别的。

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

它会依次完成「字数分析 → 拆书 → 建库 → 检索问答」，产物在 `data\out\`（章节 docx、`manifest.json`、`kb.json`）
换真实教材时，把 `.docx` 放进 `data\source\` 并替换上面的文件路径即可。

---

## 三、运行测试

提交改动前，请确保相关套件全部通过。测试均不依赖模型 Key，也不访问外网。

```powershell
# 后端：250 项
cd backend
.venv\Scripts\python.exe -m pytest

# 前端：161 项
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
| 安装扫描件 OCR 依赖（可选） | `.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt` |
| 导出教材 Markdown | `curl http://localhost:8000/api/books/<id>/markdown -o book.md` |
| 删除教材（不可恢复） | `curl -X DELETE http://localhost:8000/api/books/<id>` |
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
   （PDF 带目录书签、Word 带标题样式时章节识别最准）。旧版 `.doc` 也能直接传，
   （PDF 带目录书签、Word 带标题样式时章节识别最准）。旧版 `.doc` 在服务器装有
   LibreOffice 时也能直接传；**扫描件 PDF** 会自动走 OCR 异步识别，弹窗里显示逐页进度，
   识别完直接出现在书架；
3. 进入章节 —— 左栏教材原文、右栏 AI 讲解。原文保留原文件的**行内版式**
   （粗体、斜体、上下标、字号层级），文中的**插图与表格**按原位置显示；
   原文区顶部有**章节导航**（上一章 / 目录下拉 / 下一章），
   读完一章直接翻下一章；右上角可切换**阅读方式**：
   「滚动」整章连着看，「分页」按教材段落高度一页页翻（翻页按钮或 ← → 方向键），
   选择会记住，下次进来自动沿用。
   **拖选一段原文，选区旁会浮出「问 AI」气泡**，
   点开就是可拖动的追问浮层，可连续追问；右栏「追问线程」列表能切换回看、定位回原文。
   回答**逐字流式返回**，附带「教材依据」可一键回跳原文；依据取自**全书**（当前章节命中加权），
   跨章依据会标出章节名并可跳过去核对。
   右栏顶部是**掌握度面板**：读过的段落、提问次数实时计入，面板会列出每一项的权重与得分，
   也能手动「标记本章学完」；
4. 进入「知识地图」—— 查看跨章节沉淀的知识点卡片、**前置依赖**（实线带箭头）与**学习顺序**（虚线），
   教材里没有出现过的前置概念会单独列出；点击节点可回到对应章节原文核对。

---

## 六、常见问题

**页面能打开，但列表是示例数据、无法上传 PDF？**
`frontend\.env` 未创建或 `VITE_API_BASE_URL` 为空，前端处于内置演示数据模式。按「首次安装 · 第 2 步」创建 `.env`，再重启 `npm run dev`。

**打开页面一直转圈，或提示「连不上教材服务」？**
后端没起来或地址不对。按「日常调试启动 · 终端 1」启动后端，确认 http://localhost:8000/api/health 能打开，并检查 `frontend\.env` 的 `VITE_API_BASE_URL`。页面上的「重试」可直接重连，无需刷新。

**还没导入教材时打开首页看到什么？**
会看到「还没有教材」的引导：点「上传教材」即可；也可以先在 `backend` 目录执行 `scripts\make_demo_pdf.py` 生成团队原创的示例教材再刷新。知识地图页同样会给引导，不会一直空白或转圈。

**讲解和回答偏模板化？**
`backend\.env` 没配 `LLM_API_KEY`，后端在用规则回退。填入 DeepSeek Key 后重启后端即切换为真实推理（`/api/health` 的 `llm` 会变成 `cloud`）。

**划词提问总是答「教材中未找到直接依据」？**
这是已修的老问题。四件事都可能导致「没回答」，且后三件的症状会伪装成别的正常输出：
① 划词时选中的原文没参与检索（现已按锚点直取、作为第一条证据，检索词也带上选中原文）；
② 提示词把「片段不足以回答就拒绝」当默认出口（现改为先尽力作答，只有片段与问题
完全无关才拒绝）；③ `max_tokens` 取 900 时被模型的推理串吃掉，正文为 0 而静默回退兜底
（现为 4000）；④ 依据判据用覆盖率，**问得越详细越容易被拒**（现改为看「教材是不是在
反复讲这个概念」，与问句长短无关）。详见 `docs\后端设计文档.md` 第 5.1、5.3 节。

**答「教材中未找到直接依据」时还有救吗？**
有。回答下面会给出下一步（换个更具体的问法，或选中相关原文提问——划词追问不受依据判定
限制），并列出教材里最接近的几段原文供你判断是不是问偏了。那些段落**标注为不是回答依据**，
不与溯源锚点混同。详见 `docs\后端设计文档.md` 第 5.3 节。

**回答开头出现「未接入大模型…」或「模型这次没有返回内容…」？**
两句含义不同：前者是 `backend\.env` 没配 `LLM_API_KEY`（预期行为，`/api/health` 的 `llm`
会是 `mock`）；后者是模型**配了但这次没吐出正文**（超时、被截断、服务异常），看后端日志里
「LLM 问答失败/流式问答失败」那条 warning。两种情况都只列出教材原文并保留溯源，不会编造。

**为什么回答的依据来自其他章节？**
因为后端**每次都检索整本教材**（当前章节命中加权），而不是只看当前章节。
教材常把总述与定义放在靠前的总论章、把例题放在讲该主题的章节，只看本章就会在命中例题的
那一刻错过定义；一次取 10 段、跨章合并后再让模型提炼，回答才不会只是复述手边的几条。
命中里一旦有别的章节，界面会提示“依据取自全书，含其他章节的段落”，跨章依据按钮带章节名，
点击即跳到那一章核对原文。

**刷新页面后追问记录还在吗？**
在。每条划词追问都是一条线程（`threads` / `thread_messages`），回答与溯源信息一起持久化；
右栏「追问线程」列表可随时切回，并定位到它对应的那段原文。演示模式（未连后端）把线程存在浏览器本地。

**端口被占用（8000 / 3000）？**
后端换端口启动（如 `--port 8001`），并把 `frontend\.env` 的 `VITE_API_BASE_URL` 同步改成对应地址；前端端口可在 `frontend/vite.config.mjs` 调整。

**知识地图为空或提示不可用？**
知识地图由章节原文抽取出的知识点聚合而来，需要先有一次教材成功入库。确认已执行 `scripts\make_demo_pdf.py`，或先在主页上传一本教材。

**上传 `.doc` 报错说没装 LibreOffice？**
`.doc` 是旧版二进制 Word 格式，`python-docx` 读不了，需要本机装有 **LibreOffice**
才能转换后解析（命令名 `soffice` / `libreoffice` 均可；不在 PATH 里时用
`AI_READER_SOFFICE` 指定完整路径，见 `backend\.env.example`）。
不想装也没关系：把文件在 Word 里另存为 `.docx` 即可，
其它格式一律不受影响。上传界面会自动探测这个能力，不支持时不会让你白传一次。

**上传扫描件 PDF 后一直在识别？**
扫描件没有文本层，后端会自动转成 OCR 异步任务（进度条在「更换教材」弹窗里）。
一本 300 页的教材大约十几分钟，识别期间可以关掉弹窗继续学习，完成后会提示你。
**刷新页面也能接上进度**（任务 id 存在浏览器本地）；万一看到「已停止等待」，
那只是前端不再等，**识别可能仍在后台继续**——重新打开「更换教材」弹窗，列表会重新读一次服务端。
没装 OCR 依赖时不会静默失败，而是给出一条带 `pip install -r requirements-ocr.txt` 的提示。

**扫描件明明识别完了，「更换教材」里却找不到它？**
重新打开这个弹窗即可：每次打开都会重读一次教材列表。识别要跑几十分钟，用户中途刷新或关掉弹窗都很正常，
所以在后台完成的入库必须自己冒出来，不能等人去刷新整个页面。

**删了的教材能恢复吗？**
不能。删除会连同章节、原文段落、AI 讲解、学习进度和追问线程一起清掉，界面会先弹一个确认框。
**这是唯一会丢弃 OCR 结果的操作**——扫描件删掉就得重新上传、重新识别几十分钟；
文字版 PDF / Word / 文本重传很快，但进度和追问也不会回来。

**识别到一半会不会先入库半本书？**
不会，**全有或全无**：识别中途出错时一行都不写库，任务标为失败并说明跑到第几页。
半本书入库会让溯源指向不存在的原文，比没有更糟。

**识别途中改了后端代码（`--reload` 重启）？**
识别线程随进程结束，任务会被对账标记为「已中断，请重新上传」。这一版不支持断点续跑，
但会如实告诉你，不会一直转圈。

**上传后提示「内容可能没被完整读取」？**
解析器读不全这本教材，提示里会写清**跳过了什么**。最常见的是正文写在 **Word 表格 /
文本框 / 图片**里——这些地方的文字 `doc.paragraphs` 读不到，整本书就只剩几百字。
把内容改成普通段落（章节用「标题 1 / 标题 2」样式）后重新上传最稳；PDF 同理。
**整本是扫描图片的 PDF 不走这条路径**——它会自动转去 OCR，看不到这个提示。
另外，超过 200 页的 PDF 会**跳过表格提取**以控制导入耗时（读图不受影响），
提示里也会写明这一点。
提示随教材存进数据库，重开「更换教材」弹窗仍能在对应教材上看到标记。

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
