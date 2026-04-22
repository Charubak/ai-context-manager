"""CLI: python -m context_manager <command> [args]"""
import argparse
import json
import os
import sys
from pathlib import Path

from .extractor import ContextExtractor
from .generator import MasterContextGenerator
from .injector import ContextInjector
from .parser import ConversationParser
from .store import ConversationStore

DATA_DIR = os.getenv("DATA_DIR", "data")


def cmd_upload(args):
    store = ConversationStore(DATA_DIR)
    parser = ConversationParser()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    path = Path(args.file)
    if not path.exists():
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    meta, messages = parser.parse_file(str(path), tags=tags)
    store.save_conversation(meta, messages)

    print(f"Parsed: {meta.title}")
    print(f"  ID:       {meta.id}")
    print(f"  Messages: {meta.message_count}")
    print(f"  Tokens:   ~{meta.tokens_used}")
    print(f"  Tags:     {', '.join(meta.projects) or '(none)'}")
    return meta.id


def cmd_extract(args):
    store = ConversationStore(DATA_DIR)
    extractor = ContextExtractor()

    if args.all:
        convs = store.list_conversations()
        ids = [c.id for c in convs]
    else:
        ids = [args.id]

    for conv_id in ids:
        result = store.load_conversation(conv_id)
        if not result:
            print(f"Not found: {conv_id}", file=sys.stderr)
            continue
        meta, messages = result
        print(f"Extracting: {meta.title}...")
        ctx = extractor.extract_from_conversation(conv_id, messages)
        store.save_context(ctx)
        print(f"  Confidence: {ctx.confidence}")
        print(f"  Summary:    {ctx.summary[:120]}...")
        print(f"  Decisions:  {len(ctx.key_decisions)}")
        print(f"  Blockers:   {len(ctx.blockers)}")
        print(f"  Actions:    {len(ctx.action_items)}")


def cmd_generate(args):
    store = ConversationStore(DATA_DIR)
    generator = MasterContextGenerator()

    user_profile = {}
    if args.profile and Path(args.profile).exists():
        user_profile = json.loads(Path(args.profile).read_text())

    project_filter = args.project or None
    convs = store.list_conversations(project=project_filter)
    conv_ids = [c.id for c in convs]
    extractions = store.load_all_contexts(conv_ids)

    master = generator.generate(extractions, convs, user_profile)
    md = generator.to_markdown(master)

    output = Path(args.output) if args.output else Path(DATA_DIR) / "master_context.md"
    output.write_text(md, encoding="utf-8")
    print(f"Master context written to: {output}")
    print(f"  Conversations: {len(convs)}")
    print(f"  Projects:      {len(master.projects)}")
    print(f"  Priorities:    {len(master.current_priorities)}")
    print(f"  Learnings:     {len(master.recent_learnings)}")
    print(f"  Char count:    {len(md)} (~{len(md)//4} tokens)")

    if args.json:
        json_out = output.with_suffix(".json")
        json_out.write_text(json.dumps(master.to_dict(), indent=2))
        print(f"  JSON written:  {json_out}")


def cmd_list(args):
    store = ConversationStore(DATA_DIR)
    convs = store.list_conversations(project=args.project)
    if not convs:
        print("No conversations found.")
        return
    for c in convs:
        tags = f"  [{', '.join(c.projects)}]" if c.projects else ""
        ctx_exists = (Path(DATA_DIR) / "contexts" / f"{c.id}.json").exists()
        extracted_mark = " [extracted]" if ctx_exists else ""
        print(f"{c.date_last_modified.strftime('%Y-%m-%d')}  {c.title}{tags}{extracted_mark}")
        print(f"  id={c.id}  msgs={c.message_count}")


def cmd_run(args):
    """Upload + extract + generate in one shot."""
    conv_id = cmd_upload(args)
    args.id = conv_id
    args.all = False
    cmd_extract(args)
    args.output = None
    args.profile = None
    args.json = False
    cmd_generate(args)


def main():
    root = argparse.ArgumentParser(prog="context_manager", description="AI context manager CLI")
    sub = root.add_subparsers(dest="command")

    # upload
    p_upload = sub.add_parser("upload", help="Parse and store a conversation file")
    p_upload.add_argument("file", help="Path to conversation file (JSON or markdown)")
    p_upload.add_argument("--tags", default="", help="Comma-separated project tags")

    # extract
    p_extract = sub.add_parser("extract", help="Extract context from a stored conversation")
    p_extract.add_argument("id", nargs="?", help="Conversation ID")
    p_extract.add_argument("--all", action="store_true", help="Extract all stored conversations")

    # generate
    p_gen = sub.add_parser("generate", help="Generate master context from all extractions")
    p_gen.add_argument("--project", default="", help="Filter by project tag")
    p_gen.add_argument("--output", default="", help="Output file path (default: data/master_context.md)")
    p_gen.add_argument("--profile", default="", help="Path to user profile JSON")
    p_gen.add_argument("--json", action="store_true", help="Also write JSON output")

    # list
    p_list = sub.add_parser("list", help="List stored conversations")
    p_list.add_argument("--project", default="", help="Filter by project tag")

    # run (all-in-one)
    p_run = sub.add_parser("run", help="Upload + extract + generate in one command")
    p_run.add_argument("file", help="Path to conversation file")
    p_run.add_argument("--tags", default="", help="Comma-separated project tags")

    # serve
    p_serve = sub.add_parser("serve", help="Start the FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    args = root.parse_args()

    if args.command == "upload":
        cmd_upload(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("context_manager.api:app", host=args.host, port=args.port, reload=True)
    else:
        root.print_help()


if __name__ == "__main__":
    main()
