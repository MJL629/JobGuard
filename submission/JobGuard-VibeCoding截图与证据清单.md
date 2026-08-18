# JobGuard 求职卫士 - 截图与证据清单

> 这个文件用于指导你补齐 PPT、说明文档、海报和视频需要的证据。

## 1. 必须截图

- [ ] 项目根目录结构
- [ ] README 或项目启动说明
- [ ] 后端 `/health` 返回正常
- [ ] FastAPI `/docs` 页面
- [ ] 前端登录页
- [ ] 对话助手主动引导画像
- [ ] “加班偏好”复述确认效果
- [ ] 求职画像页持久化结果
- [ ] 简历上传成功
- [ ] 多份简历列表
- [ ] 简历解析失败时的中文提示
- [ ] 岗位推荐列表
- [ ] 不同岗位差异化推荐理由
- [ ] 岗位分析页
- [ ] 可核验来源区域
- [ ] Agent 工具调用记录
- [ ] 定向简历模板选择
- [ ] 定向简历生成结果
- [ ] `/agent-ops` 运行记录
- [ ] 后端 pytest 通过
- [ ] 前端 Vite build 通过

## 2. 建议截图命名

```text
01_project_structure.png
02_backend_health.png
03_openapi_docs.png
04_login.png
05_chat_profile_building.png
06_overtime_confirmation.png
07_profile_persisted.png
08_resume_upload.png
09_resume_list.png
10_jobs_recommendation.png
11_job_analysis.png
12_evidence_gate.png
13_agent_tool_trace.png
14_resume_template.png
15_generated_resume.png
16_agent_ops.png
17_pytest_passed.png
18_frontend_build.png
```

## 3. 需要保留的代码截图

- `backend/app/main.py`：FastAPI 入口、路由、健康检查
- `backend/app/api/__init__.py`：API 模块组织
- `backend/app/agents/graph.py` 或 `backend/app/graph/builder.py`：LangGraph 主链
- `backend/app/agents/tool_registry.py`：工具注册
- `backend/app/mcp_server.py`：MCP 服务
- `backend/app/services/job_service.py`：岗位推荐和分析
- `backend/app/services/profile_service.py`：画像持久化
- `backend/app/services/resume_file_service.py`：简历文件解析
- `backend/app/services/agent_observability_service.py`：Agent 观测
- `frontend/src/views/ChatView.vue`：对话页面
- `frontend/src/views/ProfileView.vue`：画像和简历上传
- `frontend/src/views/JobListView.vue`：岗位推荐
- `frontend/src/views/JobAnalysisView.vue`：岗位分析
- `frontend/src/views/ResumeView.vue`：定向简历
- `frontend/src/views/AgentOpsView.vue`：Agent 观测

## 4. 需要补充到说明文档的测试结果

最终提交前重新运行并截图：

```powershell
cd E:\jobguard\jobguard\backend
.\.venv\Scripts\python.exe -m pytest
```

```powershell
cd E:\jobguard\jobguard\frontend
npm run build
```

如果本地服务已启动，再截图：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
http://127.0.0.1:5173
```

如果前端端口实际是 `5174`，以实际端口为准。

## 5. 提交包安全检查

不要打包：

- `.env`
- API Key
- Cookie
- 验证码
- userKey
- 身份证信息
- 真实个人简历原件
- `node_modules`
- `.venv`
- `frontend/dist`
- `backend/data/uploads`
- `backend/output`
- `data/chroma`
- `tmp`

推荐只把最终四个材料文件打包，不直接压缩整个项目目录。

