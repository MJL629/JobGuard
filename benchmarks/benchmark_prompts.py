from __future__ import annotations

import json
from typing import Any

import tiktoken

from app.agents import background_check, job_matcher, job_parser, orchestrator, profile_agent, resume_generator


ENCODING = tiktoken.get_encoding("cl100k_base")


def _messages(agent: str, variant: int) -> list[dict[str, str]]:
    user_messages = ["我想找后端开发", "请分析这个岗位", "给我推荐 Agent 岗位"]
    resumes = [
        "张三，本科，Python 项目经验。",
        "李四，硕士，Java 与 MySQL 项目经验。",
        "王五，本科，参加过算法竞赛。",
    ]
    jobs = [
        {"company": "甲公司", "title": "后端工程师", "jd": "Python FastAPI"},
        {"company": "乙公司", "title": "算法工程师", "jd": "PyTorch NLP"},
        {"company": "丙公司", "title": "测试开发", "jd": "Python Pytest"},
    ]
    item = jobs[variant]

    if agent == "orchestrator":
        if hasattr(orchestrator, "INTENT_SYSTEM_PROMPT"):
            return [
                {"role": "system", "content": orchestrator.INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": orchestrator.INTENT_USER_PROMPT.format(
                    user_message=user_messages[variant], session_type="general"
                )},
            ]
        return [{"role": "user", "content": orchestrator.INTENT_PROMPT.format(
            user_message=user_messages[variant], session_type="general"
        )}]

    if agent == "profile_agent":
        if hasattr(profile_agent, "RESUME_PARSE_SYSTEM_PROMPT"):
            return [
                {"role": "system", "content": profile_agent.RESUME_PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": profile_agent.RESUME_PARSE_USER_PROMPT.format(
                    resume_text=resumes[variant]
                )},
            ]
        return [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON，不输出任何解释。"},
            {"role": "user", "content": profile_agent.RESUME_PARSE_PROMPT.format(resume_text=resumes[variant])},
        ]

    if agent == "job_parser":
        raw = f"公司：{item['company']}\n岗位：{item['title']}\n要求：{item['jd']}"
        if hasattr(job_parser, "JOB_EXTRACT_SYSTEM_PROMPT"):
            return [
                {"role": "system", "content": job_parser.JOB_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": job_parser.JOB_EXTRACT_USER_PROMPT.format(raw_text=raw)},
            ]
        return [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON，不输出任何解释。"},
            {"role": "user", "content": job_parser.JOB_EXTRACT_PROMPT.format(raw_text=raw)},
        ]

    if agent == "background_check":
        dynamic = {
            "job_info": json.dumps(item, ensure_ascii=False),
            "jd_analysis": json.dumps({"overtime_risk": "low"}, ensure_ascii=False),
            "company_info": f"{item['company']}公开信息",
            "online_reputation": "未获取",
            "user_profile": json.dumps({"目标": item["title"]}, ensure_ascii=False),
        }
        if hasattr(background_check, "RISK_ASSESSMENT_SYSTEM_PROMPT"):
            return [
                {"role": "system", "content": background_check.RISK_ASSESSMENT_SYSTEM_PROMPT},
                {"role": "user", "content": background_check.RISK_ASSESSMENT_USER_PROMPT.format(**dynamic)},
            ]
        return [
            {"role": "system", "content": "你是一位企业风险评估专家。只输出 JSON。"},
            {"role": "user", "content": background_check.RISK_ASSESSMENT_PROMPT.format(**dynamic)},
        ]

    if agent == "job_matcher":
        dynamic = {
            "user_profile": json.dumps({"skills": ["Python"], "variant": variant}, ensure_ascii=False),
            "company_name": item["company"], "job_title": item["title"],
            "category": "engineering", "requirements": item["jd"],
            "salary_min": 10000, "salary_max": 18000,
            "location": "广州", "jd_summary": item["jd"],
        }
        if hasattr(job_matcher, "MATCH_SYSTEM_PROMPT"):
            return [
                {"role": "system", "content": job_matcher.MATCH_SYSTEM_PROMPT},
                {"role": "user", "content": job_matcher.MATCH_USER_PROMPT.format(**dynamic)},
            ]
        return [
            {"role": "system", "content": "You are a JSON output engine."},
            {"role": "user", "content": job_matcher.MATCH_PROMPT.format(**dynamic)},
        ]

    dynamic = {
        "job_title": item["title"], "job_category": "engineering",
        "requirements": item["jd"], "project_name": f"项目{variant + 1}",
        "role": "开发者", "description": resumes[variant],
        "tech_stack": "[\"Python\"]", "highlights": "无量化结果",
        "emphasis_angle": "后端工程能力",
    }
    if hasattr(resume_generator, "PROJECT_REWRITE_SYSTEM_PROMPT"):
        return [
            {"role": "system", "content": resume_generator.PROJECT_REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": resume_generator.PROJECT_REWRITE_USER_PROMPT.format(**dynamic)},
        ]
    return [
        {"role": "system", "content": "You are a JSON output engine."},
        {"role": "user", "content": resume_generator.PROJECT_REWRITE_PROMPT.format(**dynamic)},
    ]


def _tokens(text: str) -> list[int]:
    return ENCODING.encode(text)


def _common_prefix_length(sequences: list[list[int]]) -> int:
    if not sequences:
        return 0
    limit = min(len(sequence) for sequence in sequences)
    for index in range(limit):
        token = sequences[0][index]
        if any(sequence[index] != token for sequence in sequences[1:]):
            return index
    return limit


def run(phase: str) -> dict[str, Any]:
    agents = [
        "orchestrator", "profile_agent", "job_parser",
        "background_check", "job_matcher", "resume_generator",
    ]
    results = []
    for agent in agents:
        variants = [_messages(agent, index) for index in range(3)]
        serialized = [
            "".join(f"<{message['role']}>\n{message['content']}\n" for message in messages)
            for messages in variants
        ]
        system_contents = [
            "\n".join(message["content"] for message in messages if message["role"] == "system")
            for messages in variants
        ]
        dynamic_contents = [
            "\n".join(message["content"] for message in messages if message["role"] != "system")
            for messages in variants
        ]
        prefix = _common_prefix_length([_tokens(text) for text in serialized])
        results.append({
            "agent": agent,
            "system_tokens": [len(_tokens(text)) for text in system_contents],
            "dynamic_user_context_tokens": [len(_tokens(text)) for text in dynamic_contents],
            "common_prefix_tokens": prefix,
            "dynamic_starts_at_token": prefix,
            "system_prompt_stable": len(set(system_contents)) == 1,
            "message_roles": [[message["role"] for message in messages] for messages in variants],
        })
    return {
        "phase": phase,
        "tokenizer": "tiktoken/cl100k_base",
        "tokenizer_note": "Structural proxy only; not provider-exact token counts.",
        "claim_boundary": "This measures prefix friendliness, not real prefix-cache hit rate.",
        "agents": results,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.phase), ensure_ascii=False, indent=2))
