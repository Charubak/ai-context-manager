import json
import re
from typing import Dict, List

import anthropic

from .models import ExtractedContext

EXTRACTION_PROMPT = """\
You are a context extraction assistant. Analyze the conversation below and extract structured information.

Return ONLY a valid JSON object with exactly these keys:
{
  "summary": "1-3 sentence executive summary of the conversation",
  "key_decisions": ["list of important decisions made"],
  "blockers": ["list of blockers, problems, or unresolved issues"],
  "learnings": ["list of insights, lessons, or new knowledge gained"],
  "action_items": ["list of concrete next steps or TODOs mentioned"],
  "entities": {
    "people": ["names mentioned"],
    "tools": ["software, libraries, APIs, services mentioned"],
    "projects": ["project names mentioned"],
    "companies": ["company names mentioned"]
  }
}

Rules:
- Be specific and concrete — extract actual content, not vague summaries
- If a category has nothing relevant, use an empty list
- Each item should be a complete, self-contained statement (no pronouns like "it" or "this")
- Keep each item under 120 characters

CONVERSATION:
{conversation}
"""

CODE_SNIPPET_PATTERN = re.compile(
    r"```(\w*)\n(.*?)```",
    re.DOTALL,
)


class ContextExtractor:
    def __init__(self, api_key: str = ""):
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def extract_from_conversation(self, conversation_id: str, messages: List[Dict]) -> ExtractedContext:
        if not messages:
            return ExtractedContext(conversation_id=conversation_id, confidence=0.0)

        conversation_text = self._format_messages(messages)
        code_snippets = self.extract_code_snippets(messages)

        # Truncate if very long (stay within ~12k tokens for extraction)
        max_chars = 48_000
        if len(conversation_text) > max_chars:
            conversation_text = conversation_text[:max_chars] + "\n\n[...truncated...]"

        prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            extracted = self._parse_response(raw)
            confidence = self._score_confidence(extracted, messages)

            return ExtractedContext(
                conversation_id=conversation_id,
                key_decisions=extracted.get("key_decisions", []),
                blockers=extracted.get("blockers", []),
                learnings=extracted.get("learnings", []),
                action_items=extracted.get("action_items", []),
                code_snippets=code_snippets,
                entities=extracted.get("entities", {}),
                summary=extracted.get("summary", ""),
                confidence=confidence,
            )
        except Exception as e:
            return ExtractedContext(
                conversation_id=conversation_id,
                summary=f"Extraction failed: {e}",
                confidence=0.0,
            )

    def extract_code_snippets(self, messages: List[Dict]) -> List[Dict]:
        snippets = []
        for msg in messages:
            content = msg.get("content", "")
            for match in CODE_SNIPPET_PATTERN.finditer(content):
                language = match.group(1) or "unknown"
                snippet = match.group(2).strip()
                # Grab up to 200 chars before the block as context
                start = max(0, match.start() - 200)
                context_text = content[start:match.start()].strip()
                snippets.append({
                    "language": language,
                    "snippet": snippet,
                    "context": context_text[-200:] if context_text else "",
                    "role": msg.get("role", ""),
                })
        return snippets

    def _format_messages(self, messages: List[Dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "unknown").upper()
            content = m.get("content", "")
            parts.append(f"{role}:\n{content}")
        return "\n\n---\n\n".join(parts)

    def _parse_response(self, raw: str) -> Dict:
        # Strip markdown code fences if the model wrapped the JSON
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        return json.loads(raw)

    def _score_confidence(self, extracted: Dict, messages: List[Dict]) -> float:
        score = 0.0
        if extracted.get("summary"):
            score += 0.3
        if extracted.get("key_decisions"):
            score += 0.2
        if extracted.get("action_items"):
            score += 0.2
        if extracted.get("learnings"):
            score += 0.15
        if len(messages) >= 4:
            score += 0.15
        return min(round(score, 2), 1.0)
