# AI讲师 · 教材驱动的自主学习系统

为学生与自学者打造的「教材驱动」学习系统：导入教材 → 生成学习路径 → 章节学习 →
AI 讲解与溯源问答。回答以指定教材为边界，每条回答都可回到原文核对。

## 仓库结构

```
AI_reader/
├── docs/           # 赛题要求、产品设计、后端设计文档
├── frontend/       # React + Vite 前端（主页/学习页/划词问答）
├── backend/        # FastAPI 后端（PDF 解析 / RAG 检索 / 溯源问答）
└── tools/kb-agent/ # 教材入库 Agent 原型（docx/txt → 章节 Word + RAG 知识库）
```

## 运行方式

conda deactivate
conda config --set auto_activate_base false
conda activate
### 1. 启动后端（端口 8000）

初次
```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\make_demo_pdf.py        # 生成原创示例教材（可选）
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```
之后
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
### 2. 启动前端（端口 3000）

初次
```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL='http://localhost:8000'   # 接入真实后端
npm run dev
```
之后
cd frontend
$env:VITE_API_BASE_URL='http://localhost:8000'
npm run dev

不设置 `VITE_API_BASE_URL` 时前端使用内置演示数据（纯前端模式）。
测试：后端 `.venv\Scripts\python.exe -m pytest`（15 项），前端 `npm test`（26 项）。

## 体验完整链路

1. 打开 http://localhost:3000 —— 主页展示从后端加载的教材与学习路径；
2. 点击「更换教材」→「上传」即可导入任意文本型 PDF（含目录书签最佳）；
3. 进入章节——左栏原文、右栏 AI 讲解；拖动选中原文提问，回答带「教材依据」回跳。

详细设计见 `docs/后端设计文档.md` 与 `docs/产品设计文档.md`。
