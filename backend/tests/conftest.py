import pytest


@pytest.fixture(autouse=True)
def disable_gemini_cache_by_default(monkeypatch):
    """Tests opt into a temporary cache explicitly to avoid cross-test state."""
    monkeypatch.setenv("GEMINI_CACHE_TTL_SECONDS", "0")


@pytest.fixture(autouse=True)
def accept_answers_without_calling_gemini(monkeypatch):
    """Never call the real answer-checking model from tests; tests that need a verdict override this."""
    from app import agent_tools
    from app.answer_judge import Judgement

    async def accept(question, raw_response, value, earlier):
        return Judgement(reasoning="Test stub accepts every answer.", verdict="accept", message="")
    monkeypatch.setattr(agent_tools, "judge_answer", accept)


@pytest.fixture(autouse=True)
def no_lessons_without_calling_gemini(monkeypatch):
    """Never call the real teaching model from tests; tests that need a lesson override this."""
    from app import agent_tools
    from app.teaching import Lesson

    async def nothing_to_teach(question, person_asked=""):
        return Lesson(needed=False)
    monkeypatch.setattr(agent_tools, "lesson_for", nothing_to_teach)
