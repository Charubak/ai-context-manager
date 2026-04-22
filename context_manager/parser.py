import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import ConversationMetadata


class ConversationParser:
    """Parses Claude.ai exports (JSON or markdown) into normalized messages."""

    def detect_format(self, input_data: str) -> str:
        stripped = input_data.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return "json"
        if re.search(r"^#{1,3}\s", stripped, re.MULTILINE):
            return "markdown"
        return "plaintext"

    def parse(self, source: str, file_path: str = "", tags: Optional[List[str]] = None) -> Tuple[ConversationMetadata, List[Dict]]:
        fmt = self.detect_format(source)
        if fmt == "json":
            return self.parse_json_string(source, file_path, tags)
        elif fmt == "markdown":
            return self.parse_markdown(source, file_path, tags)
        else:
            return self.parse_plaintext(source, file_path, tags)

    def parse_file(self, file_path: str, tags: Optional[List[str]] = None) -> Tuple[ConversationMetadata, List[Dict]]:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        return self.parse(content, file_path=str(path), tags=tags)

    # ── JSON (Claude.ai export format) ────────────────────────────────────────

    def parse_json_string(self, text: str, file_path: str = "", tags: Optional[List[str]] = None) -> Tuple[ConversationMetadata, List[Dict]]:
        data = json.loads(text)
        # Handle both single conversation dict and array of conversations
        if isinstance(data, list):
            data = data[0] if data else {}

        messages = self._normalize_json_messages(data.get("chat_messages", data.get("messages", [])))
        title = data.get("name", data.get("title", Path(file_path).stem or "Untitled"))
        now = datetime.now()
        created = self._parse_timestamp(data.get("created_at", now.isoformat()))
        updated = self._parse_timestamp(data.get("updated_at", now.isoformat()))

        meta = ConversationMetadata(
            id=data.get("uuid", data.get("id", str(uuid.uuid4()))),
            title=title,
            date_created=created,
            date_last_modified=updated,
            message_count=len(messages),
            tokens_used=self._estimate_tokens(messages),
            projects=tags or [],
            topics=[],
            status="active",
            file_path=file_path,
        )
        return meta, messages

    def _normalize_json_messages(self, raw: List[Dict]) -> List[Dict]:
        normalized = []
        for m in raw:
            role = m.get("sender", m.get("role", "unknown"))
            # Claude.ai uses "human"/"assistant"; normalize to standard roles
            if role == "human":
                role = "user"

            content = m.get("text", "")
            if not content and "content" in m:
                # Handle content as list of blocks (API format)
                blocks = m["content"]
                if isinstance(blocks, list):
                    parts = []
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "text":
                            parts.append(b.get("text", ""))
                        elif isinstance(b, str):
                            parts.append(b)
                    content = "\n".join(parts)
                else:
                    content = str(blocks)

            ts = m.get("created_at", m.get("timestamp", ""))
            normalized.append({"role": role, "content": content, "timestamp": ts})
        return normalized

    # ── Markdown ──────────────────────────────────────────────────────────────

    def parse_markdown(self, text: str, file_path: str = "", tags: Optional[List[str]] = None) -> Tuple[ConversationMetadata, List[Dict]]:
        lines = text.splitlines()
        title = "Untitled"
        if lines and lines[0].startswith("#"):
            title = lines[0].lstrip("#").strip()

        messages = []
        current_role: Optional[str] = None
        current_lines: List[str] = []

        # Match patterns like "**Human:**", "**Assistant:**", "Human:", "Assistant:"
        role_pattern = re.compile(r"^\*{0,2}(Human|User|Assistant|Claude)\*{0,2}:(.*)$", re.IGNORECASE)

        for line in lines[1:]:
            m = role_pattern.match(line)
            if m:
                if current_role is not None:
                    messages.append({
                        "role": current_role,
                        "content": "\n".join(current_lines).strip(),
                        "timestamp": "",
                    })
                raw_role = m.group(1).lower()
                current_role = "user" if raw_role in ("human", "user") else "assistant"
                rest = m.group(2).strip()
                current_lines = [rest] if rest else []
            elif current_role is not None:
                current_lines.append(line)

        if current_role is not None and current_lines:
            messages.append({
                "role": current_role,
                "content": "\n".join(current_lines).strip(),
                "timestamp": "",
            })

        now = datetime.now()
        meta = ConversationMetadata(
            id=str(uuid.uuid4()),
            title=title,
            date_created=now,
            date_last_modified=now,
            message_count=len(messages),
            tokens_used=self._estimate_tokens(messages),
            projects=tags or [],
            topics=[],
            status="active",
            file_path=file_path,
        )
        return meta, messages

    # ── Plaintext ─────────────────────────────────────────────────────────────

    def parse_plaintext(self, text: str, file_path: str = "", tags: Optional[List[str]] = None) -> Tuple[ConversationMetadata, List[Dict]]:
        """Treat entire text as a single user message (paste mode)."""
        now = datetime.now()
        messages = [{"role": "user", "content": text.strip(), "timestamp": ""}]
        meta = ConversationMetadata(
            id=str(uuid.uuid4()),
            title=Path(file_path).stem or "Pasted Conversation",
            date_created=now,
            date_last_modified=now,
            message_count=1,
            tokens_used=self._estimate_tokens(messages),
            projects=tags or [],
            topics=[],
            status="active",
            file_path=file_path,
        )
        return meta, messages

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_timestamp(self, ts: str) -> datetime:
        if not ts:
            return datetime.now()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
        except Exception:
            return datetime.now()

    def _estimate_tokens(self, messages: List[Dict]) -> int:
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 4  # rough approximation
