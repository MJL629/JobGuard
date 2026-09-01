# JobGuard SFT v3 多任务数据集

目标：把上一版“单一 JD 抽取 SFT”升级为更贴近 JobGuard 业务闭环的领域多任务 SFT。当前版本不再推进 DPO/PPO，主线收敛到 SFT。

## 数据来源

- 项目内人工种子岗位：`backend/data/seed_jobs*.json`
- 北京市人社公开岗位 CSV：`data/北京市人力资源和社会保障局-单位招聘岗位信息.csv`

构造脚本不会调用大模型，也不会引入 mock 结果。公开 CSV 生成的标签属于 `silver_rule`，只能用于工程训练和对比；正式晋升前需要人工复核一批 gold 样本。

## 任务类型

每条 JD 生成 4 类 SFT 样本：

1. `jd_extract`：岗位结构化抽取，覆盖公司、岗位、类别、地点、薪资、学历、经验、技能、福利、风险标签。
2. `job_classify`：岗位大类/细分方向分类，并输出证据关键词。
3. `risk_label`：识别培训引流、KPI/销售伪装、加班强度、薪资异常等 JD 风险话术。
4. `skill_normalize`：将 JD 中的技术词标准化，例如 LLM、Agent、RAG、LangGraph、FastAPI、MySQL。

## 当前生成结果

运行：

```powershell
cd E:\jobguard\jobguard
backend\.venv\Scripts\python.exe backend\scripts\build_sft_v3_dataset.py --max-jobs 500
backend\.venv\Scripts\python.exe backend\scripts\validate_sft_v3_dataset.py
```

输出：

- `dataset/train.jsonl`
- `dataset/val.jsonl`
- `dataset/test.jsonl`
- `dataset/gold_review_candidates.jsonl`
- `dataset/manifest.json`
- `dataset/validation_report.json`

当前版本为 500 条 JD、2000 条 SFT 样本，训练/验证/测试为 1400/300/300。

## 人工参与点

下一步需要人工参与的是 `dataset/gold_review_candidates.jsonl`。建议先复核 100 条候选样本，重点检查：

- 岗位类别和细分方向是否合理；
- 技能标签是否漏标或误标；
- 风险话术是否过度标记；
- 薪资、地点、学历、经验是否抽取正确；
- 无法核验的社保、仲裁、工商异常是否保持 unknown/未核验。

复核完成后，可把 `label_quality` 从 `silver_rule` 升级为 `gold_human_reviewed`，再训练正式 SFT v3。

## 简历口径

当前可以说：

> 构建 JobGuard 领域多任务 SFT v3 数据集，基于 500 条 JD 生成 2000 条训练样本，覆盖 JD 抽取、岗位分类、风险话术识别和技能标准化；采用 70/15/15 划分，并输出 100 条高优先级 gold 复核候选，为后续提升结构化抽取和风险识别能力提供数据基础。

在人工复核和训练完成前，不建议写“显著提升准确率”。
