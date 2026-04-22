from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional
import json
import uuid


@dataclass
class ConversationMetadata:
    id: str
    title: str
    date_created: datetime
    date_last_modified: datetime
    message_count: int
    tokens_used: int
    projects: List[str]
    topics: List[str]
    status: str  # "active", "archived", "reference"
    file_path: str

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["date_created"] = self.date_created.isoformat()
        d["date_last_modified"] = self.date_last_modified.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "ConversationMetadata":
        d = d.copy()
        d["date_created"] = datetime.fromisoformat(d["date_created"])
        d["date_last_modified"] = datetime.fromisoformat(d["date_last_modified"])
        return cls(**d)


@dataclass
class ExtractedContext:
    conversation_id: str
    key_decisions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    learnings: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    code_snippets: List[Dict] = field(default_factory=list)
    entities: Dict[str, List[str]] = field(default_factory=dict)
    summary: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ExtractedContext":
        return cls(**d)


@dataclass
class ProjectContext:
    name: str
    status: str  # "active", "paused", "shipped"
    description: str
    tech_stack: List[str] = field(default_factory=list)
    related_conversations: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)
    current_blockers: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    progress_pct: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MasterContext:
    generated_at: datetime
    version: str
    personal_info: Dict
    projects: Dict[str, ProjectContext]
    skills: List[str]
    current_priorities: List[str]
    recent_learnings: List[str]
    all_conversations: List[ConversationMetadata]
    next_update: datetime

    def to_dict(self) -> Dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
            "personal_info": self.personal_info,
            "projects": {k: v.to_dict() for k, v in self.projects.items()},
            "skills": self.skills,
            "current_priorities": self.current_priorities,
            "recent_learnings": self.recent_learnings,
            "all_conversations": [c.to_dict() for c in self.all_conversations],
            "next_update": self.next_update.isoformat(),
        }
