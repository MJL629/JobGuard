# 🛡️ JobGuard（求职卫士）

> 面向求职者的多智能体岗位筛选与简历优化系统

## 项目简介

JobGuard 是一个基于多智能体协作的求职辅助系统，帮助计算机方向的应届生和职场新人：

- 🔍 **避雷**：识别垃圾岗位、虚假宣传、高风险企业
- 📝 **精准投递**：根据目标岗位自动生成针对性简历和招呼语
- 🎯 **智能推荐**：基于用户画像匹配适合的岗位

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Element Plus |
| 后端 | FastAPI (Python 3.11+) |
| 多智能体 | LangGraph |
| RAG | LangChain + Chroma |
| 数据库 | MySQL 8.0 |
| LLM | 智谱 GLM-4-Flash + DeepSeek V3 |
| Embedding | BGE-M3 (SiliconFlow) |

## 快速开始

### 1. 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 2. 启动数据库

```bash
docker-compose up -d mysql
```

### 3. 配置 API Key

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 4. 启动后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

## 项目结构

```
jobguard/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── api/      # API 路由
│   │   ├── models/   # 数据库模型
│   │   ├── agents/   # LangGraph Agent
│   │   ├── graph/    # LangGraph 图
│   │   ├── rag/      # RAG 知识库
│   │   ├── llm/      # LLM 统一调用层
│   │   └── services/ # 业务逻辑
│   └── requirements.txt
├── frontend/         # Vue 3 前端
│   └── src/
│       ├── views/    # 页面
│       ├── components/ # 组件
│       ├── stores/   # Pinia 状态管理
│       └── api/      # API 封装
├── data/             # 数据库初始化脚本
├── docs/             # 文档
└── docker-compose.yml
```

## 文档

- [产品需求文档](docs/产品需求文档.md)
- [技术方案设计](docs/技术方案设计.md)

## 开发状态

🟡 **骨架阶段** - 项目基础框架已搭建，核心 Agent 逻辑待实现。

## License

MIT
