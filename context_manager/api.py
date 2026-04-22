import json
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse

from .extractor import ContextExtractor
from .generator import MasterContextGenerator
from .injector import ContextInjector
from .models import MasterContext
from .parser import ConversationParser
from .store import ConversationStore

DATA_DIR = os.getenv("DATA_DIR", "data")

app = FastAPI(title="Context Manager API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ConversationStore(DATA_DIR)
parser = ConversationParser()
extractor = ContextExtractor()
generator = MasterContextGenerator()
injector = ContextInjector()


# ── Upload & Parse ─────────────────────────────────────────────────────────────

@app.post("/api/conversations/upload")
async def upload_conversation(
    file: UploadFile = File(...),
    tags: str = Form(default=""),
):
    """Upload a conversation export (JSON or markdown). Returns parsed metadata."""
    content = (await file.read()).decode("utf-8")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        meta, messages = parser.parse(content, file_path=file.filename or "", tags=tag_list)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")

    store.save_conversation(meta, messages)
    return {
        "id": meta.id,
        "title": meta.title,
        "message_count": meta.message_count,
        "tokens_used": meta.tokens_used,
        "projects": meta.projects,
        "status": "parsed",
    }


# ── Extract Context ────────────────────────────────────────────────────────────

@app.post("/api/conversations/{conv_id}/extract")
async def extract_context(conv_id: str):
    """Run Claude API extraction on a stored conversation."""
    result = store.load_conversation(conv_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    meta, messages = result

    ctx = extractor.extract_from_conversation(conv_id, messages)
    store.save_context(ctx)

    preview = (
        f"{len(ctx.key_decisions)} key decisions, "
        f"{len(ctx.blockers)} blockers, "
        f"{len(ctx.learnings)} learnings, "
        f"{len(ctx.action_items)} action items"
    )
    return {
        "extraction": ctx.to_dict(),
        "confidence": ctx.confidence,
        "preview": preview,
    }


# ── Master Context ─────────────────────────────────────────────────────────────

@app.post("/api/master-context/generate")
async def generate_master_context(body: dict):
    """Generate master context from stored conversations.

    Body: {include_conversations?: [...ids], include_projects?: [...tags],
           format?: "markdown"|"json", user_profile?: {...}}
    """
    include_convs: Optional[List[str]] = body.get("include_conversations")
    include_projects: Optional[List[str]] = body.get("include_projects")
    fmt: str = body.get("format", "markdown")
    user_profile: dict = body.get("user_profile", {})

    conversations = store.list_conversations()
    if include_convs:
        conversations = [c for c in conversations if c.id in include_convs]
    if include_projects:
        conversations = [c for c in conversations if any(p in c.projects for p in include_projects)]

    conv_ids = [c.id for c in conversations]
    extractions = store.load_all_contexts(conv_ids)

    master = generator.generate(extractions, conversations, user_profile)

    if fmt == "json":
        return master.to_dict()

    md = generator.to_markdown(master)
    return {"context": master.to_dict(), "markdown": md}


@app.get("/api/master-context/export")
async def export_master_context(format: str = "markdown", project: Optional[str] = None):
    """Download current master context as markdown or JSON."""
    conversations = store.list_conversations(project=project)
    conv_ids = [c.id for c in conversations]
    extractions = store.load_all_contexts(conv_ids)
    master = generator.generate(extractions, conversations)

    if format == "json":
        return JSONResponse(content=master.to_dict())

    md = generator.to_markdown(master)
    return PlainTextResponse(content=md, media_type="text/markdown")


# ── List & Manage ─────────────────────────────────────────────────────────────

@app.get("/api/conversations")
async def list_conversations(
    project: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    convs = store.list_conversations(project=project, status=status)[:limit]
    total_messages = sum(c.message_count for c in convs)
    total_tokens = sum(c.tokens_used for c in convs)
    dates = [c.date_created for c in convs] if convs else []

    return {
        "conversations": [c.to_dict() for c in convs],
        "total": len(convs),
        "aggregated": {
            "total_messages": total_messages,
            "estimated_tokens": total_tokens,
            "date_range": [
                min(dates).isoformat() if dates else None,
                max(dates).isoformat() if dates else None,
            ],
        },
    }


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    result = store.load_conversation(conv_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    meta, messages = result
    ctx = store.load_context(conv_id)
    return {
        "metadata": meta.to_dict(),
        "messages": messages,
        "extraction": ctx.to_dict() if ctx else None,
    }


@app.patch("/api/conversations/{conv_id}/tags")
async def update_tags(conv_id: str, body: dict):
    projects = body.get("projects", [])
    topics = body.get("topics", [])
    ok = store.update_tags(conv_id, projects, topics)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "updated"}
