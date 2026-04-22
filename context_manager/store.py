"""Simple JSON file store — no database dependency for Phase 1."""
import json
from pathlib import Path
from typing import Dict, List, Optional

from .models import ConversationMetadata, ExtractedContext


class ConversationStore:
    def __init__(self, data_dir: str = "data"):
        self.base = Path(data_dir)
        self.conv_dir = self.base / "conversations"
        self.ctx_dir = self.base / "contexts"
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        self.ctx_dir.mkdir(parents=True, exist_ok=True)

    # ── Conversations ──────────────────────────────────────────────────────────

    def save_conversation(self, meta: ConversationMetadata, messages: List[Dict]) -> None:
        record = {"metadata": meta.to_dict(), "messages": messages}
        path = self.conv_dir / f"{meta.id}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))

    def load_conversation(self, conv_id: str) -> Optional[tuple]:
        path = self.conv_dir / f"{conv_id}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        meta = ConversationMetadata.from_dict(record["metadata"])
        return meta, record["messages"]

    def list_conversations(self, project: Optional[str] = None, status: Optional[str] = None) -> List[ConversationMetadata]:
        results = []
        for path in sorted(self.conv_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            record = json.loads(path.read_text())
            meta = ConversationMetadata.from_dict(record["metadata"])
            if project and project not in meta.projects:
                continue
            if status and meta.status != status:
                continue
            results.append(meta)
        return results

    def update_tags(self, conv_id: str, projects: List[str], topics: List[str]) -> bool:
        result = self.load_conversation(conv_id)
        if not result:
            return False
        meta, messages = result
        meta.projects = projects
        meta.topics = topics
        self.save_conversation(meta, messages)
        return True

    # ── Extracted Contexts ─────────────────────────────────────────────────────

    def save_context(self, context: ExtractedContext) -> None:
        path = self.ctx_dir / f"{context.conversation_id}.json"
        path.write_text(json.dumps(context.to_dict(), indent=2, ensure_ascii=False))

    def load_context(self, conv_id: str) -> Optional[ExtractedContext]:
        path = self.ctx_dir / f"{conv_id}.json"
        if not path.exists():
            return None
        return ExtractedContext.from_dict(json.loads(path.read_text()))

    def load_all_contexts(self, conv_ids: Optional[List[str]] = None) -> List[ExtractedContext]:
        results = []
        paths = self.ctx_dir.glob("*.json")
        for path in paths:
            ctx = ExtractedContext.from_dict(json.loads(path.read_text()))
            if conv_ids is None or ctx.conversation_id in conv_ids:
                results.append(ctx)
        return results
