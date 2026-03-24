"""Intent classification — rule-based keyword matching with LLM fallback stub."""

import re

INTENT_PATTERNS = {
    "git_operation": {
        "keywords": ["git", "commit", "branch", "merge", "diff", "push", "pull", "rebase", "stash", "checkout", "log"],
        "patterns": [r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b", r"\bdiff\b"],
    },
    "file_operation": {
        "keywords": ["read", "open", "show", "cat", "find", "search", "glob", "grep", "list files", "write file", "create file", "edit file"],
        "patterns": [r"\bread\b.*\.\w+", r"\bopen\b.*\.\w+", r"\bshow\b.*\.\w+", r"\bfind\b.*file", r"\bgrep\b", r"\bglob\b"],
    },
    "shell_command": {
        "keywords": ["run", "execute", "npm", "pip", "make", "docker", "curl", "wget", "ls", "mkdir", "cd"],
        "patterns": [r"\brun\b", r"\bexecute\b", r"\bnpm\b", r"\bpip\b", r"\bdocker\b", r"\bmake\b"],
    },
    "code_task": {
        "keywords": ["fix", "implement", "refactor", "add feature", "write code", "debug", "bug", "error", "build", "create function", "modify", "update code"],
        "patterns": [r"\bfix\b", r"\bimplement\b", r"\brefactor\b", r"\bbug\b", r"\bdebug\b", r"\berror\b"],
    },
    "knowledge_query": {
        "keywords": ["what does", "how does", "explain", "why", "what is", "describe", "documentation", "how to"],
        "patterns": [r"\bwhat\s+does\b", r"\bhow\s+does\b", r"\bexplain\b", r"\bwhat\s+is\b", r"\bdescribe\b"],
    },
}

# "conversation" is the fallback — no patterns needed


class IntentParser:
    def classify(self, text: str) -> dict:
        """Classify user input into an intent type with confidence score."""
        text_lower = text.lower().strip()
        best_type = "conversation"
        best_score = 0.0

        for intent_type, patterns in INTENT_PATTERNS.items():
            score = 0.0
            # Keyword matching
            keyword_hits = sum(1 for kw in patterns["keywords"] if kw in text_lower)
            if keyword_hits > 0:
                score += min(keyword_hits * 0.3, 0.6)
            # Regex pattern matching
            regex_hits = sum(1 for p in patterns["patterns"] if re.search(p, text_lower))
            if regex_hits > 0:
                score += min(regex_hits * 0.2, 0.4)

            if score > best_score:
                best_score = score
                best_type = intent_type

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
