"""Intent classification — rule-based keyword matching with LLM fallback stub."""

import re

# keyword routing table
INTENT_PATTERNS = {
    "knowledge_query": {
        "keywords": ["what does", "how does", "explain", "what is", "describe", "documentation", "how to", "how do", "why does", "why is", "what are", "tell me about",
                     # the KB as an OBJECT. "Search the knowledge base ..." is a question,
                     # not a filesystem search -- see the second pattern below (#6724).
                     "knowledge base", "knowledge-base"],
        "patterns": [r"\bwhat\s+(?:does|is|are|models|the|a)\b", r"\bhow\s+(?:do|does|to|did|can)\b", r"\bexplain\b", r"\bdescribe\b", r"\bwhy\s+(?:does|is|are|do)\b", r"\btell\s+me\b",
                     # A LOOKUP VERB whose object is the knowledge base / memory / mistakes.
                     # Without this, "Search the knowledge base for X" scores only on
                     # file_operation's "search" and is handled as a filesystem grep --
                     # locally, with no LLM, no task row and nothing in the Live Dispatch
                     # feed. The request vanishes, which is worse than failing (#6724).
                     r"\b(?:search|find|look\s*up|recall|check|query|dig\s+up)\b[^.]{0,50}?"
                     r"\b(?:knowledge[\s-]*base|kb|memory|memories|mistakes?|vault|"
                     r"documentation|docs|prior\s+art|past\s+sessions?)\b"],
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


def _keyword_regex(keyword: str) -> "re.Pattern":
    """Word-boundary matcher for one keyword, tolerating simple inflections.

    `keyword in text` is a SUBSTRING test, and that is how a knowledge-base question
    became a filesystem search (#6724): the file_operation keyword "cat" matched inside
    "fabri*cat*ed", handing file_operation two hits (0.6) against knowledge_query's 0.5.
    Measured — 13 of the table's keywords fire inside ordinary English:
        cat -> fabricated, category, catalog      log  -> technology, logic, login
        run -> prune, truncate                    read -> already, thread, spreadsheet
        diff -> difficult, different              merge-> emerged, emergency

    The optional suffix is deliberate: a bare `\bbug\b` would stop matching "bugs",
    and `\berror\b` would stop matching "errors", so a strict boundary fix would trade
    one silent misroute for another. Allowing s/es/ed/ing keeps the inflections that
    genuinely mean the keyword while still refusing the unrelated words above.

    Leading/trailing boundaries are applied only next to alphanumerics, so a keyword
    like "c++" is matched literally rather than by a boundary that can never hold.
    """
    escaped = re.escape(keyword)
    lead = r"\b" if keyword[:1].isalnum() else ""
    trail = r"(?:s|es|ed|ing|ings)?\b" if keyword[-1:].isalnum() else ""
    return re.compile(lead + escaped + trail)


# "the object of this lookup is the knowledge base / our memory", compiled once.
# Shared by the knowledge_query pattern list and the shadow rule in classify() so the
# two can never drift into disagreeing about what a KB question looks like.
_KB_OBJECT_RE = re.compile(
    r"\b(?:search|find|look\s*up|recall|check|query|dig\s+up)\b[^.]{0,50}?"
    r"\b(?:knowledge[\s-]*base|kb|memory|memories|mistakes?|vault|"
    r"documentation|docs|prior\s+art|past\s+sessions?)\b"
)

# Compiled once at import — classify() runs on every turn.
_KEYWORD_RES = {
    name: [_keyword_regex(k) for k in cfg["keywords"]]
    for name, cfg in INTENT_PATTERNS.items()
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
            keyword_hits = sum(1 for rx in _KEYWORD_RES[intent_type] if rx.search(text_lower))
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

        # A lookup whose OBJECT is the knowledge base is a question, whatever verb it
        # opened with. This SHADOWS the file layer rather than out-scoring it, because
        # scoring cannot settle it: "search memory for what we decided" gives
        # file_operation 0.30 from the bare verb "search" and knowledge_query only 0.20,
        # so the KB reading loses on arithmetic while being obviously right. #6724 asked
        # for exactly this shadow.
        #
        # Scoped deliberately to the TOOL intents. A code_task that happens to mention
        # memory ("write a function that frees the memory buffer") is left alone --
        # those do not silently vanish, which is the harm being prevented here.
        if best_type in ("file_operation", "shell_command") and _KB_OBJECT_RE.search(text_lower):
            best_type = "knowledge_query"
            best_score = max(best_score, 0.6)

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
