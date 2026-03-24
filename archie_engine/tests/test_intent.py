import pytest
from archie_engine.intent import IntentParser


@pytest.fixture
def parser():
    return IntentParser()


def test_classify_code_task(parser):
    result = parser.classify("fix the authentication bug in login.py")
    assert result["type"] == "code_task"
    assert 0.0 <= result["confidence"] <= 1.0


def test_classify_file_operation(parser):
    result = parser.classify("read the contents of config.py")
    assert result["type"] == "file_operation"


def test_classify_git_operation(parser):
    result = parser.classify("show me the git diff")
    assert result["type"] == "git_operation"


def test_classify_shell_command(parser):
    result = parser.classify("run npm test")
    assert result["type"] == "shell_command"


def test_classify_conversation_fallback(parser):
    result = parser.classify("how are you today?")
    assert result["type"] == "conversation"


def test_classify_knowledge_query(parser):
    result = parser.classify("what does the auth middleware do?")
    assert result["type"] == "knowledge_query"


def test_classify_returns_required_fields(parser):
    result = parser.classify("do something")
    assert "type" in result
    assert "confidence" in result
    assert "raw_input" in result
    assert "entities" in result


def test_classify_ambiguous_low_confidence(parser):
    result = parser.classify("hmm interesting")
    assert result["type"] == "conversation"
    assert result["confidence"] < 0.5


def test_entity_extraction_files(parser):
    result = parser.classify("read config.py and main.rs")
    assert "files" in result["entities"]
    assert "config.py" in result["entities"]["files"]
