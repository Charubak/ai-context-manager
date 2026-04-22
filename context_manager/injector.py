from .generator import MasterContextGenerator
from .models import MasterContext


class ContextInjector:
    def __init__(self):
        self.generator = MasterContextGenerator()

    def format_for_chatgpt_custom_instructions(self, context: MasterContext, max_chars: int = 12000) -> str:
        return self.generator.to_chatgpt_instructions(context, max_chars)

    def format_for_claude_system_prompt(self, context: MasterContext, max_tokens: int = 2000) -> str:
        # ~4 chars per token approximation
        max_chars = max_tokens * 4
        md = self.generator.to_markdown(context)
        if len(md) <= max_chars:
            return md
        return md[:max_chars] + "\n\n[...context truncated to fit token limit...]"

    def format_for_api_injection(self, context: MasterContext, model: str = "claude") -> dict:
        if "gpt" in model.lower():
            system_prompt = self.format_for_chatgpt_custom_instructions(context)
        else:
            system_prompt = self.format_for_claude_system_prompt(context)

        return {
            "model": model,
            "system_prompt": system_prompt,
            "context_doc": self.generator.to_markdown(context),
        }
