from app.agents.background_check import (
    RISK_ASSESSMENT_SYSTEM_PROMPT,
    RISK_ASSESSMENT_USER_PROMPT,
)
from app.agents.job_matcher import MATCH_SYSTEM_PROMPT, MATCH_USER_PROMPT
from app.agents.job_parser import JOB_EXTRACT_SYSTEM_PROMPT, JOB_EXTRACT_USER_PROMPT
from app.agents.orchestrator import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT
from app.agents.profile_agent import RESUME_PARSE_SYSTEM_PROMPT, RESUME_PARSE_USER_PROMPT
from app.agents.resume_generator import (
    PROJECT_REWRITE_SYSTEM_PROMPT,
    PROJECT_REWRITE_USER_PROMPT,
)


def test_fixed_system_prompts_do_not_contain_dynamic_placeholders():
    pairs = [
        (INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT, "{user_message}"),
        (RESUME_PARSE_SYSTEM_PROMPT, RESUME_PARSE_USER_PROMPT, "{resume_text}"),
        (JOB_EXTRACT_SYSTEM_PROMPT, JOB_EXTRACT_USER_PROMPT, "{raw_text}"),
        (RISK_ASSESSMENT_SYSTEM_PROMPT, RISK_ASSESSMENT_USER_PROMPT, "{job_info}"),
        (MATCH_SYSTEM_PROMPT, MATCH_USER_PROMPT, "{user_profile}"),
        (PROJECT_REWRITE_SYSTEM_PROMPT, PROJECT_REWRITE_USER_PROMPT, "{description}"),
    ]

    for system_prompt, user_prompt, placeholder in pairs:
        assert placeholder not in system_prompt
        assert placeholder in user_prompt
        assert len(system_prompt) > 20
