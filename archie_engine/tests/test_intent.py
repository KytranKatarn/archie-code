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


def test_classify_question_not_shell(parser):
    """Natural language questions must NOT be classified as shell_command."""
    result = parser.classify("What models are available on Ollama?")
    assert result["type"] != "shell_command", f"Got {result['type']} — questions should not be shell"
    assert result["type"] in ("knowledge_query", "conversation")


def test_classify_how_question_is_knowledge(parser):
    """'How do I...' questions should be knowledge_query."""
    result = parser.classify("How do I configure the database connection?")
    assert result["type"] == "knowledge_query"


def test_classify_what_is_question(parser):
    """'What is...' questions should be knowledge_query."""
    result = parser.classify("What is the Bridge dispatcher?")
    assert result["type"] == "knowledge_query"


def test_classify_list_files_is_file_operation(parser):
    """'list all files in src/' should be file_operation, not conversation."""
    result = parser.classify("list all files in src/")
    assert result["type"] == "file_operation"


def test_classify_run_explicit_is_shell(parser):
    """'run npm install' should still be shell_command."""
    result = parser.classify("run npm install")
    assert result["type"] == "shell_command"


def test_classify_docker_is_shell(parser):
    """'docker compose up' should be shell_command."""
    result = parser.classify("docker compose up -d")
    assert result["type"] == "shell_command"
