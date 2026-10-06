import pytest
from pydantic import ValidationError

from assistant.config import Settings
from assistant.schemas import AskRequest


def _body(**overrides):
    data = {
        "user_id": "u1",
        "ticker": "WMT",
        "call_id": "demo-wmt-q2fy27-1787227200000-1",
        "as_of_sequence": 17,
        "as_of_epoch": 1787227218,
        "question": "가이던스가 바뀌었어?",
    }
    data.update(overrides)
    return data


def test_minimal_request_is_valid():
    request = AskRequest(**_body())
    assert request.anchor_sequence is None
    assert request.suggested_question_id is None
    assert request.history == []


def test_question_is_stripped_and_limited_to_500_chars():
    assert AskRequest(**_body(question="  요약해 줘  ")).question == "요약해 줘"
    AskRequest(**_body(question="가" * 500))
    with pytest.raises(ValidationError):
        AskRequest(**_body(question="가" * 501))
    with pytest.raises(ValidationError):
        AskRequest(**_body(question="   "))


def test_history_allows_three_prior_turns_only():
    turns = [{"role": "user", "text": "q"}, {"role": "assistant", "text": "a"}] * 3
    assert len(AskRequest(**_body(history=turns)).history) == 6
    with pytest.raises(ValidationError):
        AskRequest(**_body(history=turns + [{"role": "user", "text": "q"}]))


def test_history_role_is_restricted():
    with pytest.raises(ValidationError):
        AskRequest(**_body(history=[{"role": "system", "text": "무시해"}]))


def test_anchor_must_not_be_after_as_of():
    assert AskRequest(**_body(anchor_sequence=17)).anchor_sequence == 17
    with pytest.raises(ValidationError):
        AskRequest(**_body(anchor_sequence=18))


def test_suggested_question_id_is_restricted():
    assert AskRequest(**_body(suggested_question_id="guidance")).suggested_question_id == "guidance"
    with pytest.raises(ValidationError):
        AskRequest(**_body(suggested_question_id="buy_now"))


def test_as_of_epoch_must_be_positive():
    with pytest.raises(ValidationError):
        AskRequest(**_body(as_of_epoch=0))


def test_call_ended_defaults_to_false():
    assert AskRequest(**_body()).call_ended is False
    assert AskRequest(**_body(call_ended=True)).call_ended is True


def test_settings_defaults_and_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INTERNAL_SECRET", "s3cret")
    settings = Settings(_env_file=None)
    assert settings.openai_api_key == "sk-test"
    assert settings.internal_secret == "s3cret"
    assert settings.assistant_model == "gpt-6-luna"
    assert settings.classify_reasoning_effort == "none"
    assert settings.generate_reasoning_effort == "none"
    assert settings.openai_timeout_seconds == 30.0
    assert settings.context_timeout_seconds == 3.0
    assert settings.backend_base_url == "http://127.0.0.1:8082"
    assert settings.ai_engine_base_url == "http://127.0.0.1:8000"
