"""Intent classification — rule-based keyword matching with LLM fallback stub."""

import re

# keyword routing table
INTENT_PATTERNS = {
    "knowledge_query": {
        "keywords": ["what does", "how does", "explain", "what is", "describe", "documentation", "how to", "how do", "why does", "why is", "what are", "tell me about"],
        "patterns": [r"\bwhat\s+(?:does|is|are|models|the|a)\b", r"\bhow\s+(?:do|does|to|did|can)\b", r"\bexplain\b", r"\bdescribe\b", r"\bwhy\s+(?:does|is|are|do)\b", r"\btell\s+me\b"],
        "priority": 10,
    },
    "file_operation": {
        "keywords": ["read", "open", "show", "cat", "find", "search", "glob", "grep", "list files", "write file", "create file", "edit file", "list all files"],
        "patterns": [r"\bread\b.*\.\w+", r"\bopen\b.*\.\w+", r"\bshow\b.*\.\w+", r"\bfind\b.*file", r"\bgrep\b", r"\bglob\b", r"\blist\b.*\bfiles?\b"],
        "priority": 8,
    },
    "git_operation": {
        "keywords": ["git", "commit", "branch", "merge", "diff", "push", "pull", "rebase", "stash", "checkout", "log"],
        "patterns": [r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b", r"\bdiff\b"],
        "priority": 7,
    },
    # ⚠️ The keyword list used to be the WHOLE test, and it missed the most ordinary
    # way anyone asks for code. Measured live 2026-09-11 against the running engine:
    # "write a python function that reverses a linked list" matched NOTHING — "write
    # code" is not "write a python function", and "create function" is not "a python
    # function". Score 0, and per classify() "zero score never beats conversation", so
    # a pure coding request classified as `conversation` and dispatched with the
    # `general` capability. Task #6703 recorded it verbatim:
    #     "general: write a python function that reverses a linked list"
    #
    # Literal keywords cannot carry this alone — the phrasing space is open. The added
    # patterns pair an AUTHORING VERB with a CODE NOUN, and separately recognise a
    # named language beside a code noun. That catches natural phrasing without
    # swallowing questions ABOUT code: "what is the function of X" still scores higher
    # on knowledge_query, which also outranks this on priority (10 > 6).
    "code_task": {
        "keywords": [
            "fix", "implement", "refactor", "add feature", "write code", "debug", "bug",
            "error", "build", "create function", "modify", "update code",
            # ordinary code nouns — a request naming one is nearly always code work
            "function", "unit test", "algorithm", "snippet", "docstring", "type hint",
        ],
        "patterns": [
            r"\bfix\b", r"\bimplement\b", r"\brefactor\b", r"\bbug\b", r"\bdebug\b", r"\berror\b",
            # authoring verb + code noun — "write a python function", "add a method"
            r"\b(?:write|create|add|generate|make|build|implement)\b[^.]{0,40}?"
            r"\b(?:function|class|method|script|program|module|endpoint|component|test|parser|algorithm|query)\b",
            # named language beside a code noun — "a python script that ..."
            r"\b(?:python|javascript|typescript|java|rust|golang|go|sql|bash|shell|ruby|php|c\+\+)\b"
            r"[^.]{0,30}\b(?:function|class|script|code|method|snippet|program|module)\b",
        ],
        "priority": 6,
    },
    "shell_command": {
        "keywords": ["run", "execute", "npm", "pip", "make", "docker", "curl", "wget", "mkdir"],
        "patterns": [r"\brun\s+\S+", r"\bexecute\s+\S+", r"\bnpm\s+\w+", r"\bpip\s+\w+", r"\bdocker\s+\w+", r"\bmake\b"],
        "priority": 5,
    },
}


class IntentParser:
    def classify(self, text: str) -> dict:
        """Classify user input into an intent type with confidence score."""
        text_lower = text.lower().strip()
        best_type = "conversation"
        best_score = 0.0
        best_priority = 0

        for intent_type, config in INTENT_PATTERNS.items():
            score = 0.0
            # Keyword matching
            keyword_hits = sum(1 for kw in config["keywords"] if kw in text_lower)
            if keyword_hits > 0:
                score += min(keyword_hits * 0.3, 0.6)
            # Regex pattern matching
            regex_hits = sum(1 for p in config["patterns"] if re.search(p, text_lower))
            if regex_hits > 0:
                score += min(regex_hits * 0.2, 0.4)

            priority = config.get("priority", 0)

            # Higher score wins. On tie, higher priority wins. Zero score never beats conversation.
            if score > 0 and (score > best_score or (score == best_score and priority > best_priority)):
                best_score = score
                best_type = intent_type
                best_priority = priority

        # Confidence: scale 0-1, conversation fallback gets low confidence
        confidence = min(best_score, 1.0) if best_type != "conversation" else 0.2

        return {
            "type": best_type,
            "confidence": confidence,
            "raw_input": text,
            "entities": self._extract_entities(text),
        }

    def _extract_entities(self, text: str) -> dict:
        """Extract useful entities (file paths, git refs, etc.) from input."""
        entities = {}
        # File paths (e.g., "config.py", "src/main.rs", "./foo/bar.txt")
        file_matches = re.findall(r'[\w./\-]+\.\w+', text)
        if file_matches:
            entities["files"] = file_matches
        # Git refs
        git_ref = re.findall(r'\b(?:main|master|HEAD|[a-f0-9]{7,40})\b', text)
        if git_ref:
            entities["git_refs"] = git_ref
        return entities
