from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import ConversationMetadata, ExtractedContext, MasterContext, ProjectContext


class MasterContextGenerator:
    def generate(
        self,
        extractions: List[ExtractedContext],
        conversations: List[ConversationMetadata],
        user_profile: Optional[Dict] = None,
        version: str = "1.0",
    ) -> MasterContext:
        profile = user_profile or {}
        meta_by_id = {c.id: c for c in conversations}

        projects: Dict[str, ProjectContext] = {}
        all_decisions: List[str] = []
        all_learnings: List[str] = []
        all_blockers: List[str] = []
        all_actions: List[str] = []
        all_tools: List[str] = []

        for ext in extractions:
            conv_meta = meta_by_id.get(ext.conversation_id)
            project_tags = conv_meta.projects if conv_meta else []

            for tag in project_tags:
                if tag not in projects:
                    projects[tag] = ProjectContext(
                        name=tag,
                        status="active",
                        description="",
                        related_conversations=[],
                    )
                p = projects[tag]
                p.related_conversations.append(ext.conversation_id)
                p.key_decisions.extend(ext.key_decisions)
                p.current_blockers.extend(ext.blockers)
                p.next_steps.extend(ext.action_items)

            all_decisions.extend(ext.key_decisions)
            all_learnings.extend(ext.learnings)
            all_blockers.extend(ext.blockers)
            all_actions.extend(ext.action_items)
            all_tools.extend(ext.entities.get("tools", []))

        # Deduplicate while preserving order
        def dedup(items: List[str]) -> List[str]:
            seen = set()
            result = []
            for item in items:
                normalized = item.lower().strip()
                if normalized not in seen:
                    seen.add(normalized)
                    result.append(item)
            return result

        for p in projects.values():
            p.key_decisions = dedup(p.key_decisions)
            p.current_blockers = dedup(p.current_blockers)
            p.next_steps = dedup(p.next_steps)

        return MasterContext(
            generated_at=datetime.now(),
            version=version,
            personal_info=profile,
            projects=projects,
            skills=dedup(profile.get("skills", []) + dedup(all_tools)),
            current_priorities=dedup(all_actions)[:10],
            recent_learnings=dedup(all_learnings)[:15],
            all_conversations=conversations,
            next_update=datetime.now() + timedelta(weeks=1),
        )

    def to_markdown(self, context: MasterContext) -> str:
        lines = []
        lines.append("# Master Context")
        lines.append(f"_Generated: {context.generated_at.strftime('%Y-%m-%d %H:%M')} · v{context.version}_")
        lines.append("")

        # Personal info
        if context.personal_info:
            lines.append("## About")
            for k, v in context.personal_info.items():
                if isinstance(v, list):
                    lines.append(f"**{k.replace('_', ' ').title()}:** {', '.join(v)}")
                else:
                    lines.append(f"**{k.replace('_', ' ').title()}:** {v}")
            lines.append("")

        # Current priorities
        if context.current_priorities:
            lines.append("## Current Priorities")
            for item in context.current_priorities:
                lines.append(f"- {item}")
            lines.append("")

        # Projects
        if context.projects:
            lines.append("## Projects")
            for name, project in context.projects.items():
                lines.append(f"### {project.name} `{project.status}`")
                if project.description:
                    lines.append(project.description)
                if project.tech_stack:
                    lines.append(f"**Stack:** {', '.join(project.tech_stack)}")
                if project.key_decisions:
                    lines.append("**Key decisions:**")
                    for d in project.key_decisions[:5]:
                        lines.append(f"- {d}")
                if project.current_blockers:
                    lines.append("**Blockers:**")
                    for b in project.current_blockers[:3]:
                        lines.append(f"- {b}")
                if project.next_steps:
                    lines.append("**Next steps:**")
                    for s in project.next_steps[:5]:
                        lines.append(f"- {s}")
                lines.append("")

        # Recent learnings
        if context.recent_learnings:
            lines.append("## Recent Learnings")
            for l in context.recent_learnings:
                lines.append(f"- {l}")
            lines.append("")

        # Skills / tools
        if context.skills:
            lines.append("## Tools & Skills")
            lines.append(", ".join(context.skills))
            lines.append("")

        # Conversation index
        if context.all_conversations:
            lines.append("## Conversation Index")
            lines.append(f"Total: {len(context.all_conversations)} conversations")
            for conv in sorted(context.all_conversations, key=lambda c: c.date_last_modified, reverse=True)[:20]:
                date_str = conv.date_last_modified.strftime("%Y-%m-%d")
                tags = f" [{', '.join(conv.projects)}]" if conv.projects else ""
                lines.append(f"- `{date_str}` {conv.title}{tags} ({conv.message_count} msgs)")
            lines.append("")

        lines.append(f"_Next update suggested: {context.next_update.strftime('%Y-%m-%d')}_")
        return "\n".join(lines)

    def to_chatgpt_instructions(self, context: MasterContext, max_chars: int = 12000) -> str:
        """Format for ChatGPT custom instructions (condensed)."""
        md = self.to_markdown(context)
        if len(md) <= max_chars:
            return md
        # Trim conversation index section if needed
        cutoff = md.find("## Conversation Index")
        if cutoff > 0:
            md = md[:cutoff].strip()
        return md[:max_chars]
