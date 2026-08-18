# JobGuard 启动与截图执行清单

> 目标：用于补齐说明文档、PPT、海报和演示视频中的真实截图。  
> 原则：只截真实运行画面，不截 Mock 结果冒充已完成功能。

## 1. 启动顺序

### 第一步：启动 MySQL

在项目根目录打开 PowerShell：

```powershell
cd E:\jobguard\jobguard
docker-compose up -d mysql
```

检查容器：

```powershell
docker ps
```

### 第二步：启动后端

打开第二个 PowerShell：

```powershell
cd E:\jobguard\jobguard\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址：

```text
http://127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

健康检查：

```text
http://127.0.0.1:8000/health
```

### 第三步：启动前端

打开第三个 PowerShell：

```powershell
cd E:\jobguard\jobguard\frontend
npm run dev
```

终端会显示实际端口，通常是：

```text
http://127.0.0.1:5173
```

如果 5173 被占用，可能是：

```text
http://127.0.0.1:5174
```

以后端和前端终端实际输出为准。

## 2. 启动后先验证

请按顺序打开并截图：

| 编号 | 地址 | 截图目的 |
|---|---|---|
| 01 | `http://127.0.0.1:8000/health` | 证明后端和数据库可用 |
| 02 | `http://127.0.0.1:8000/docs` | 证明 FastAPI OpenAPI 可访问 |
| 03 | `http://127.0.0.1:5173/login` 或实际端口 | 登录页 |
| 04 | `http://127.0.0.1:5173/chat` | 对话助手 |
| 05 | `http://127.0.0.1:5173/profile` | 求职画像 |
| 06 | `http://127.0.0.1:5173/jobs` | 岗位推荐 |
| 07 | `http://127.0.0.1:5173/resume` | 定向简历 |
| 08 | `http://127.0.0.1:5173/agent-ops` | Agent 观测 |

如果前端端口是 5174，把上面的 5173 全部换成 5174。

## 3. 必须截图的演示流程

### 3.1 登录

截图：

- 登录页
- 登录成功后的首页或对话页

用途：

- 证明项目有权限管理，而不是所有人共用固定 user_id。

### 3.2 对话构建画像

在 `/chat` 输入：

```text
我想找后端开发，期望 15K-20K，广州或深圳。我可以接受偶尔正常加班，但不接受长期高强度加班。我还做过一个 JobGuard 项目，使用 Python、FastAPI 和 LangGraph。
```

等待系统回复后截图：

- AI 复述“偶尔正常加班可以，但不接受长期高强度加班”
- AI 继续追问项目、比赛、实习、证书等信息

然后输入：

```text
正确
```

截图：

- 确认保存回复
- `/profile` 中画像字段更新

### 3.3 简历上传

在 `/profile` 上传一份脱敏简历。

截图：

- 上传按钮和文件选择
- 上传成功或“已保存/解析中/需要复核”状态
- 简历列表
- 画像是否被补充

如果解析失败，也要截图，因为说明文档里可以写“失败时有明确中文提示，不假成功”。

### 3.4 岗位推荐

打开 `/jobs`。

截图：

- 岗位总数或列表
- 推荐理由
- 匹配分/暂不评分/证据覆盖率/需要确认项
- 不同岗位不是完全相同理由

注意：

- 如果仍有“暂不评分”，这是合理的，说明证据不足时系统不显示虚假百分比。
- 如果发现重复岗位，截图留作“问题与后续优化”，不要放在“已完成效果”页。

### 3.5 岗位分析

打开一个岗位详情，例如：

```text
/jobs/analysis/某个岗位ID
```

截图：

- 分析摘要
- JD 原文风险
- 官方招聘记录
- 可核验来源
- 受访问控制/未核验字段
- Agent 工具调用记录

重点截这句话类型：

```text
未核验 / 受访问控制 / 尚未接入可核验来源
```

用途：

- 证明项目有“证据门禁”，不会让模型虚构外部事实。

### 3.6 定向简历

打开 `/resume`。

截图：

- 目标岗位选择
- 模板选择
- 生成按钮
- 生成历史
- 下载 DOCX/PDF/Markdown 按钮
- 生成失败时的中文错误提示

如果生成时间较长，录视频时可以先提前生成一份，再展示生成历史。

### 3.7 Agent 观测

打开 `/agent-ops`。

截图：

- LangGraph 图
- 工具列表
- Agent 运行记录
- 工具调用记录
- 成功率、失败步骤、耗时

用途：

- 对应评分标准中的“可观测性与评估体系”。

## 4. 测试截图

### 后端测试

```powershell
cd E:\jobguard\jobguard\backend
.\.venv\Scripts\python.exe -m pytest
```

截图终端最后结果，例如：

```text
xxx passed
```

### 前端构建

```powershell
cd E:\jobguard\jobguard\frontend
npm run build
```

截图：

- 构建成功
- 如果有 chunk size warning，可以保留，说明功能不受影响，后续可做拆包优化。

## 5. 截图命名建议

```text
01_backend_health.png
02_fastapi_docs.png
03_login.png
04_chat_profile_intro.png
05_overtime_confirmation.png
06_profile_persisted.png
07_resume_upload.png
08_resume_list_or_parse_status.png
09_jobs_recommendation.png
10_job_score_reason.png
11_job_analysis_summary.png
12_evidence_gate_sources.png
13_tool_trace.png
14_resume_template_select.png
15_resume_generate_result.png
16_agent_ops_graph.png
17_agent_ops_runs.png
18_pytest_passed.png
19_frontend_build.png
```

## 6. 不建议截图的内容

- `.env`
- API Key
- Cookie
- 验证码
- userKey
- 身份证
- 真实个人简历全文
- 浏览器保存的账号密码
- 第三方网站登录后的个人中心

