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
- `dataset/gold_review_sheet.csv`
- `dataset/manifest.json`
- `dataset/validation_report.json`
- `dataset/eval_self_check_report.json`

当前版本为 500 条 JD、2000 条 SFT 样本，训练/验证/测试为 1400/300/300。

数据集校验结果：

- assistant JSON 合法率：100%
- 必需字段覆盖率：100%
- 测试集 self-check：300/300 样本通过。注意 self-check 只说明评估脚本和标签格式一致，不代表模型效果。

## 人工参与点

下一步需要人工参与的是 `dataset/gold_review_sheet.csv`。建议先复核 100 条候选样本，重点检查：

- 岗位类别和细分方向是否合理；
- 技能标签是否漏标或误标；
- 风险话术是否过度标记；
- 薪资、地点、学历、经验是否抽取正确；
- 无法核验的社保、仲裁、工商异常是否保持 unknown/未核验。

复核完成后，可把 `label_quality` 从 `silver_rule` 升级为 `gold_human_reviewed`，再训练正式 SFT v3。

## 训练与评估入口

GPU 服务器安装训练依赖：

```bash
pip install -r backend/finetune/jobguard_sft_v3/training_requirements.txt
```

先跑 smoke：

```bash
python backend/scripts/train_sft_v3_lora.py --smoke
```

正式训练默认配置见：

```text
backend/finetune/jobguard_sft_v3/sft_lora_config.json
```

模型预测文件可用如下格式保存：

```json
{"id":"sftv3_xxx","prediction":"{\"job_category\":\"技术\"}"}
```

评估：

```bash
python backend/scripts/eval_sft_v3_outputs.py \
  --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
  --predictions backend/finetune/jobguard_sft_v3/output/predictions.jsonl \
  --output backend/finetune/jobguard_sft_v3/output/eval_report.json
```

评估指标包括 JSON 合法率、必需字段覆盖率、字段准确率、Skill Precision/Recall/F1 和 Risk Precision/Recall/F1。

## 已完成实验：Qwen2.5-7B LoRA SFT r=16

2026-09-01 在 AutoDL GPU 环境完成 r=16 LoRA SFT：

- 训练样本：1400
- 验证样本：300
- 测试样本：300
- 训练 epoch：2
- 训练步数：350
- 训练耗时：873.23 秒
- train loss：0.5676
- eval loss：1.4770

测试集自动评估结果见：

```text
backend/finetune/jobguard_sft_v3/results/full_r16_test_eval.json
```

核心结果：

- JSON 合法率：100%
- 必填字段成功率：100%
- 字段准确率：93.98%
- Skill F1：93.58%
- Risk F1：87.33%

注意：该实验说明 SFT 模型在 JobGuard 自建结构化任务上具备稳定输出能力；仍需要 Base Qwen、DeepSeek/GLM 等基线对照来证明“相对提升”。

## 下一步：基线对比实验

### 1. GPU 上跑 Base Qwen 对照

如果服务器已有模型：

```bash
cd /root/autodl-tmp/jobguard-current

python backend/scripts/predict_sft_v3_outputs.py \
  --base-model /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
  --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
  --output /root/autodl-tmp/jobguard_sft_v3_outputs/base_qwen/test_predictions.jsonl \
  --max-new-tokens 256

python backend/scripts/eval_sft_v3_outputs.py \
  --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
  --predictions /root/autodl-tmp/jobguard_sft_v3_outputs/base_qwen/test_predictions.jsonl \
  --output /root/autodl-tmp/jobguard_sft_v3_outputs/base_qwen/test_eval.json
```

### 2. API 上跑商业模型对照

以 DeepSeek 为例：

```bash
cd /root/autodl-tmp/jobguard-current
export DEEPSEEK_API_KEY="你的真实 Key"

python backend/scripts/predict_sft_v3_api.py \
  --provider deepseek \
  --model deepseek-chat \
  --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
  --output /root/autodl-tmp/jobguard_sft_v3_outputs/deepseek/test_predictions.jsonl \
  --max-tokens 256

python backend/scripts/eval_sft_v3_outputs.py \
  --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
  --predictions /root/autodl-tmp/jobguard_sft_v3_outputs/deepseek/test_predictions.jsonl \
  --output /root/autodl-tmp/jobguard_sft_v3_outputs/deepseek/test_eval.json
```

### 3. 生成横向对比表

```bash
python backend/scripts/summarize_sft_v3_baselines.py \
  --run base_qwen=/root/autodl-tmp/jobguard_sft_v3_outputs/base_qwen/test_eval.json \
  --run sft_r16=/root/autodl-tmp/jobguard_sft_v3_outputs/full_r16/test_eval.json \
  --run deepseek=/root/autodl-tmp/jobguard_sft_v3_outputs/deepseek/test_eval.json \
  --output-md /root/autodl-tmp/jobguard_sft_v3_outputs/baseline_comparison.md \
  --output-csv /root/autodl-tmp/jobguard_sft_v3_outputs/baseline_comparison.csv
```

## 简历口径

当前可以说：

> 构建 JobGuard 领域多任务 SFT v3 数据集，基于 500 条 JD 生成 2000 条训练样本，覆盖 JD 抽取、岗位分类、风险话术识别和技能标准化；采用 70/15/15 划分，基于 Qwen2.5-7B 完成 LoRA SFT r=16 训练，在 300 条测试集上实现 JSON 合法率 100%、必填字段成功率 100%、字段准确率 93.98%、Skill F1 93.58%、Risk F1 87.33%，形成“数据构造—训练—预测—自动评估”的后训练实验闭环。

在 Base Qwen 和商业 API 基线对照完成前，不建议写“显著优于某模型”。
