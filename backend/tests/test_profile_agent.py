"""
用户画像 Agent 单元测试

注意：LLM 调用需要真实 API Key 配置。
未配置时，仅测试非 LLM 依赖的逻辑。
"""

import json

import pytest
from app.agents.profile_agent import profile_agent


class TestProfileAgent:
    """用户画像 Agent 测试"""

    def test_clean_json_basic(self):
        """测试 JSON 清理"""
        text = '```json\n{"name": "test"}\n```'
        result = profile_agent._clean_json(text)
        assert result == '{"name": "test"}'

    def test_clean_json_no_wrapper(self):
        """测试无包装的 JSON"""
        text = '{"name": "test"}'
        result = profile_agent._clean_json(text)
        assert result == '{"name": "test"}'

    def test_check_completeness_empty(self):
        """测试空画像完整度"""
        result = profile_agent.check_completeness({})
        assert result["completeness"] == 0
        assert len(result["missing"]) > 0
        assert result["ready"] is False

    def test_check_completeness_basic(self):
        """测试基本画像完整度"""
        profile = {
            "degree": "本科",
            "major": "计算机科学",
            "school": "清华大学",
            "graduation_year": 2024,
            "full_name": "张三",
            "current_city": "北京",
            "expected_salary_min": 15000,
            "expected_salary_max": 25000,
            "preferred_locations": ["北京", "杭州"],
            "preferred_job_types": ["后端开发"],
            "weekend_preference": "必须双休",
            "overtime_tolerance": "偶尔",
            "labor_intensity": "接受中等",
            "company_scale_pref": "大厂",
            "experiences": [{"title": "课程项目", "actions": "完成后端接口", "role": "开发"}],
            "skills": [{"skill_name": "Python"}],
        }
        result = profile_agent.check_completeness(profile)
        assert result["completeness"] >= 60
        assert result["ready"] is True

    def test_profile_is_not_ready_without_any_real_experience(self):
        profile = {
            "degree": "本科", "major": "计算机", "school": "某大学",
            "graduation_year": 2026, "expected_salary_min": 10000,
            "expected_salary_max": 15000, "preferred_locations": ["广州"],
            "preferred_job_types": ["后端开发"], "weekend_preference": "必须双休",
            "overtime_tolerance": "偶尔", "labor_intensity": "排斥高强度",
            "company_scale_pref": "不限", "remote_work": "混合",
            "skills": [{"skill_name": "Python"}],
        }
        assert profile_agent.check_completeness(profile)["ready"] is False

    def test_check_completeness_with_projects(self):
        """测试带项目的画像完整度"""
        profile = {
            "degree": "本科",
            "major": "计算机科学",
            "school": "清华大学",
            "graduation_year": 2024,
            "full_name": "张三",
            "current_city": "北京",
            "expected_salary_min": 15000,
            "expected_salary_max": 25000,
            "preferred_locations": ["北京"],
            "preferred_job_types": ["后端开发"],
            "weekend_preference": "必须双休",
            "overtime_tolerance": "偶尔",
            "labor_intensity": "接受中等",
            "projects": [{"name": "项目1"}, {"name": "项目2"}, {"name": "项目3"}],
            "skills": [{"skill_name": "Python"}, {"skill_name": "Java"}, {"skill_name": "Go"}],
        }
        result = profile_agent.check_completeness(profile)
        assert result["completeness"] > 70  # 项目+技能加分

    def test_get_missing_fields_empty(self):
        """测试缺失字段检测"""
        missing = profile_agent._get_missing_fields({})
        assert "求职方向" in missing
        assert "期望薪资范围" in missing
        assert "希望工作的城市" in missing

    def test_get_missing_fields_partial(self):
        """测试部分字段已填"""
        info = {
            "preferred_job_types": ["后端开发"],
            "expected_salary_min": 15000,
            "expected_salary_max": 25000,
        }
        missing = profile_agent._get_missing_fields(info)
        assert "求职方向" not in missing
        assert "期望薪资范围" not in missing
        assert "希望工作的城市" in missing

    def test_fallback_question_follows_missing_order(self):
        missing = profile_agent._get_missing_fields({})
        question = profile_agent._fallback_question(missing)
        assert "哪一类岗位" in question

    def test_rule_based_extraction_covers_core_preferences(self):
        updates = profile_agent._extract_rule_based_updates(
            "我想找广州或深圳的后端岗位，期望 15K-22K，必须双休，"
            "偶尔可以加班，偏好中型公司，也可以混合办公。"
        )

        assert updates["preferred_locations"] == ["广州", "深圳"]
        assert updates["preferred_job_types"] == ["后端开发"]
        assert updates["expected_salary_min"] == 15000
        assert updates["expected_salary_max"] == 22000
        assert updates["weekend_preference"] == "必须双休"
        assert updates["overtime_tolerance"] == "偶尔"
        assert updates["company_scale_pref"] == "中型"
        assert updates["remote_work"] == "混合"

    def test_rule_based_extraction_respects_negative_city(self):
        updates = profile_agent._extract_rule_based_updates("不想去北京，只考虑上海")
        assert updates["preferred_locations"] == ["上海"]

    def test_semantic_guard_does_not_generalize_high_intensity_rejection(self):
        updates = profile_agent._apply_semantic_guards(
            "我不接受高强度加班",
            {"overtime_tolerance": "不接受", "labor_intensity": "排斥高强度"},
            {"overtime_tolerance": "偶尔"},
        )

        assert updates == {"labor_intensity": "排斥高强度"}

    def test_semantic_guard_keeps_explicit_occasional_acceptance(self):
        updates = profile_agent._apply_semantic_guards(
            "我不接受长期高强度加班，但偶尔正常加班可以接受",
            {"overtime_tolerance": "不接受"},
            {},
        )

        assert updates == {
            "overtime_tolerance": "偶尔",
            "labor_intensity": "排斥高强度",
        }

    def test_string_null_values_are_filtered(self):
        assert profile_agent._normalize_updates({
            "overtime_tolerance": "null",
            "remote_work": "unknown",
            "preferred_locations": ["上海", "null"],
        }) == {"preferred_locations": ["上海"]}

    def test_workload_summary_preserves_frequency_and_intensity(self):
        summary = profile_agent._build_completion_message({
            "overtime_tolerance": "偶尔",
            "labor_intensity": "排斥高强度",
        })

        assert "偶尔、短期" in summary
        assert "长期或高强度" in summary
        assert "加班接受度：不接受" not in summary

    def test_high_intensity_constraint_requires_confirmation(self):
        confirmation = profile_agent.build_constraint_confirmation(
            "我不接受高强度加班",
            {"labor_intensity": "排斥高强度"},
            {"overtime_tolerance": "偶尔"},
        )

        assert confirmation is not None
        assert confirmation["updates"] == {"labor_intensity": "排斥高强度"}
        assert "偶尔" in confirmation["message"]
        assert confirmation["raw_evidence"] == "我不接受高强度加班"

    @pytest.mark.asyncio
    async def test_extract_updates_includes_existing_profile(self, monkeypatch):
        captured = {}

        async def fake_chat(messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return '{"preferred_locations": ["上海"]}'

        monkeypatch.setattr("app.agents.profile_agent.llm_gateway.chat", fake_chat)
        updates = await profile_agent.extract_updates(
            [
                {"role": "assistant", "content": "你希望在哪工作？"},
                {"role": "user", "content": "改成上海吧"},
            ],
            {"preferred_locations": ["北京"]},
        )

        assert updates == {"preferred_locations": ["上海"]}
        assert "北京" in captured["prompt"]
        assert "改成上海吧" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_extract_updates_does_not_repeat_stale_confirmed_constraint(self, monkeypatch):
        async def fake_chat(messages, **kwargs):
            return json.dumps({
                "preferred_job_types": ["Agent应用研发"],
                "company_scale_pref": "无所谓",
                "overtime_tolerance": "偶尔",
                "labor_intensity": "排斥高强度",
            }, ensure_ascii=False)

        monkeypatch.setattr("app.agents.profile_agent.llm_gateway.chat", fake_chat)
        updates = await profile_agent.extract_updates(
            [
                {"role": "user", "content": "我偶尔可以加班，但不接受长期高强度加班"},
                {"role": "assistant", "content": "公司规模偏好大厂、中型还是初创？"},
                {"role": "user", "content": "公司其实都行，更希望岗位对口，我想做 Agent 方向"},
            ],
            {"overtime_tolerance": "偶尔", "labor_intensity": "排斥高强度"},
        )

        assert updates == {
            "preferred_job_types": ["Agent应用研发"],
            "company_scale_pref": "无所谓",
        }

    def test_turn_acknowledgement_connects_company_and_direction(self):
        message = profile_agent.build_turn_acknowledgement({
            "preferred_job_types": ["Agent应用研发"],
            "company_scale_pref": "无所谓",
        })

        assert "Agent应用研发" in message
        assert "公司规模不设限制" in message
        assert "岗位内容是否真正对口" in message

    def test_expired_confirmation_message_cannot_reactivate_old_fields(self):
        updates = profile_agent._ground_updates_in_latest_turn(
            "公司规模不限，我更看重岗位对口，目标还是 Agent 应用研发。",
            "为了避免误解，我的理解是你可以偶尔加班。这个理解正确吗？回复“正确”。",
            {
                "preferred_job_types": ["Agent应用研发"],
                "company_scale_pref": "无所谓",
                "overtime_tolerance": "偶尔",
                "labor_intensity": "排斥高强度",
            },
            {
                "preferred_job_types": ["Agent应用研发"],
                "company_scale_pref": "无所谓",
            },
        )

        assert updates == {
            "preferred_job_types": ["Agent应用研发"],
            "company_scale_pref": "无所谓",
        }

    def test_build_completion_message(self):
        """测试完成提示消息"""
        info = {
            "preferred_job_types": ["后端开发", "AI Infra"],
            "expected_salary_min": 15000,
            "expected_salary_max": 25000,
            "preferred_locations": ["北京", "杭州"],
            "weekend_preference": "必须双休",
            "overtime_tolerance": "偶尔",
        }
        msg = profile_agent._build_completion_message(info)
        assert "后端开发" in msg
        assert "15K" in msg
        assert "北京" in msg
        assert "双休" in msg

    def test_detect_resume_content(self):
        """测试简历内容检测（从 chat.py 中的函数）"""
        from app.api.chat import _detect_resume_content

        # 短文本不应该是简历
        assert _detect_resume_content("我想找一份Java后端的工作") is False

        # 包含教育背景关键词的长文本应该是简历
        resume_text = """
        Education
        2020-2024 Tsinghua University Computer Science Bachelor
        
        Project Experience
        E-commerce Microservice Platform
        Backend developer, using Java Spring Boot + MySQL
        Implemented microservice architecture handling millions of daily requests
        
        Professional Skills
        Java, Python, Spring Boot, MySQL, Redis
        """ * 3  # 扩展到 200+ 字
        assert _detect_resume_content(resume_text) is True

    def test_resume_fallback_only_extracts_explicit_facts(self):
        parsed = profile_agent._parse_resume_fallback(
            """姓名：张三
毕业院校：示例大学
专业：软件工程
学历：本科
毕业年份：2025
项目名称：求职辅助系统
技能：Python、FastAPI、MySQL、Docker
"""
        )

        assert parsed["full_name"] == "张三"
        assert parsed["school"] == "示例大学"
        assert parsed["major"] == "软件工程"
        assert parsed["graduation_year"] == 2025
        assert parsed["projects"][0]["project_name"] == "求职辅助系统"
        assert {skill["skill_name"] for skill in parsed["skills"]} >= {
            "Python", "FastAPI", "MySQL"
        }

    def test_clean_json_accepts_explanation_and_trailing_comma(self):
        cleaned = profile_agent._clean_json('解析如下：```json\n{"degree":"本科",}\n```')
        assert json.loads(cleaned) == {"degree": "本科"}

    def test_deep_interview_progresses_and_persists_dimensions(self):
        first = profile_agent.next_deep_interview_question({}, {})
        assert first["dimension"] == "experience_inventory"

        answered = profile_agent.record_deep_interview_answer(
            first["state"], "我还做过一个没有写进简历的课程项目"
        )
        second = profile_agent.next_deep_interview_question({}, answered)

        assert "experience_inventory" in second["state"]["explored_dimensions"]
        assert second["dimension"] == "internship_work"
        assert second["state"]["depth_score"] > 0

    def test_deep_interview_allows_explicit_skip_without_repeating(self):
        first = profile_agent.next_deep_interview_question({}, {})
        skipped = profile_agent.record_deep_interview_answer(first["state"], "没有")
        second = profile_agent.next_deep_interview_question({}, skipped)

        assert "experience_inventory" in second["state"]["skipped_dimensions"]
        assert second["dimension"] != "experience_inventory"

    def test_resume_followups_connect_parsed_project_to_profile_questions(self):
        questions = profile_agent.resume_follow_up_questions(
            {"experiences": []},
            {"projects": [{"project_name": "JobGuard", "highlights": None}]},
        )

        assert len(questions) == 3
        assert any("JobGuard" in item and "亲自完成" in item for item in questions)
        assert any("尚未写进" in item for item in questions)

    def test_no_resume_education_can_be_extracted_from_dialogue(self):
        updates = profile_agent._extract_rule_based_updates(
            "我是2026年毕业的本科应届生，学校是示例大学，软件工程专业"
        )

        assert updates["degree"] == "本科"
        assert updates["school"] == "示例大学"
        assert updates["major"] == "软件工程"
        assert updates["graduation_year"] == 2026
        assert updates["years_of_experience"] == 0

    def test_missing_fields_asks_education_for_user_without_resume(self):
        missing = profile_agent._get_missing_fields({
            "preferred_job_types": ["后端开发"],
            "expected_salary_min": 15000,
            "expected_salary_max": 20000,
            "preferred_locations": ["广州"],
        })

        assert "教育背景" in missing
        assert "学历" in profile_agent._fallback_question(missing)
