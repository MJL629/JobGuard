from app.api.chat import _flatten_profile


def test_flatten_profile_keeps_preferences_and_evidence():
    flattened = _flatten_profile({
        "basic": {"degree": "本科"},
        "preferences": {"preferred_locations": ["广州"]},
        "projects": [{"project_name": "JobGuard"}],
        "skills": [{"skill_name": "Python"}],
        "education": [{"school": "测试大学"}],
    })

    assert flattened["degree"] == "本科"
    assert flattened["preferred_locations"] == ["广州"]
    assert flattened["projects"][0]["project_name"] == "JobGuard"
    assert flattened["skills"][0]["skill_name"] == "Python"
