"""
用户画像 Agent 单元测试

注意：LLM 调用需要真实 API Key 配置。
未配置时，仅测试非 LLM 依赖的逻辑。
"""

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
        }
        result = profile_agent.check_completeness(profile)
        assert result["completeness"] >= 60
        assert result["ready"] is True

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
