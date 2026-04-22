"""CLI: python -m context_manager <command> [args]"""
import argparse
import json
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from .extractor import ContextExtractor
from .generator import MasterContextGenerator
from .parser import ConversationParser
from .store import ConversationStore

DATA_DIR = os.getenv("DATA_DIR", "data")


# ── Core helpers ──────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif system == "Linux":
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        elif system == "Windows":
            subprocess.run(["clip"], input=text.encode(), check=True)
        else:
            return False
        return True
    except Exception:
        return False


def _find_conversation_files(path: Path) -> list[Path]:
    """Return all JSON/markdown conversation files from a path (file, dir, or zip)."""
    if zipfile.is_zipfile(path):
        extract_dir = path.parent / (path.stem + "_extracted")
        with zipfile.ZipFile(path) as zf:
            zf.extractall(extract_dir)
        path = extract_dir

    if path.is_file():
        return [path]

    files = list(path.rglob("*.json")) + list(path.rglob("*.md"))
    # Filter out obvious non-conversation files
    return [f for f in files if f.stat().st_size > 200]


def _progress(current: int, total: int, label: str) -> None:
    bar_len = 30
    filled = int(bar_len * current / total) if total else bar_len
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total}  {label:<40}", end="", flush=True)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_to_chatgpt(args):
    """
    The one-command workflow:
      python -m context_manager to-chatgpt <export.zip or folder>

    - Unzips if needed
    - Parses all conversations
    - Extracts context via Claude API
    - Generates master context markdown
    - Copies to clipboard
    """
    source = Path(args.source).expanduser()
    if not source.exists():
        print(f"Error: not found: {source}", file=sys.stderr)
        sys.exit(1)

    store = ConversationStore(DATA_DIR)
    parser = ConversationParser()
    extractor = ContextExtractor()
    generator = MasterContextGenerator()

    # 1. Find files
    print(f"Finding conversations in {source.name}...")
    files = _find_conversation_files(source)
    if not files:
        print("No conversation files found.", file=sys.stderr)
        sys.exit(1)
    print(f"  Found {len(files)} file(s)\n")

    # 2. Parse
    print("Parsing conversations...")
    parsed_ids = []
    skipped = 0
    for i, f in enumerate(files):
        _progress(i + 1, len(files), f.name)
        try:
            meta, messages = parser.parse_file(str(f))
            if meta.message_count == 0:
                skipped += 1
                continue
            store.save_conversation(meta, messages)
            parsed_ids.append(meta.id)
        except Exception:
            skipped += 1
    print(f"\n  Parsed {len(parsed_ids)} conversations ({skipped} skipped)\n")

    if not parsed_ids:
        print("Nothing to extract.", file=sys.stderr)
        sys.exit(1)

    # 3. Extract context
    print("Extracting context (calling Claude API)...")
    extracted = []
    for i, conv_id in enumerate(parsed_ids):
        result = store.load_conversation(conv_id)
        if not result:
            continue
        meta, messages = result
        _progress(i + 1, len(parsed_ids), meta.title[:40])
        ctx = extractor.extract_from_conversation(conv_id, messages)
        store.save_context(ctx)
        extracted.append(ctx)
    print(f"\n  Extracted {len(extracted)} contexts\n")

    # 4. Generate master context
    print("Generating master context...")
    convs = store.list_conversations()
    convs = [c for c in convs if c.id in parsed_ids]
    master = generator.generate(extracted, convs)
    md = generator.to_chatgpt_instructions(master)

    # 5. Save file
    out_path = Path(DATA_DIR) / "master_context.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    # 6. Copy to clipboard
    copied = _copy_to_clipboard(md)

    token_estimate = len(md) // 4
    print(f"  {len(convs)} conversations → {token_estimate} tokens\n")
    print("=" * 50)
    print("Done!")
    print(f"  File saved: {out_path}")
    if copied:
        print("  Copied to clipboard ✓")
        print()
        print("  → Open ChatGPT → your profile → Customize ChatGPT")
        print('  → Paste into "What would you like ChatGPT to know about you?"')
    else:
        print(f"  (Copy {out_path} manually — clipboard copy unavailable)")
    print("=" * 50)


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
    print(f"Parsed: {meta.title}  ({meta.message_count} messages)  id={meta.id}")
    return meta.id


def cmd_extract(args):
    store = ConversationStore(DATA_DIR)
    extractor = ContextExtractor()
    ids = [c.id for c in store.list_conversations()] if args.all else [args.id]
    for conv_id in ids:
        result = store.load_conversation(conv_id)
        if not result:
            print(f"Not found: {conv_id}", file=sys.stderr)
            continue
        meta, messages = result
        print(f"Extracting: {meta.title}...")
        ctx = extractor.extract_from_conversation(conv_id, messages)
        store.save_context(ctx)
        print(f"  confidence={ctx.confidence}  decisions={len(ctx.key_decisions)}  actions={len(ctx.action_items)}")


def cmd_generate(args):
    store = ConversationStore(DATA_DIR)
    generator = MasterContextGenerator()
    user_profile = {}
    if args.profile and Path(args.profile).exists():
        user_profile = json.loads(Path(args.profile).read_text())
    convs = store.list_conversations(project=args.project or None)
    conv_ids = [c.id for c in convs]
    extractions = store.load_all_contexts(conv_ids)
    master = generator.generate(extractions, convs, user_profile)
    md = generator.to_markdown(master)
    output = Path(args.output) if args.output else Path(DATA_DIR) / "master_context.md"
    output.write_text(md, encoding="utf-8")
    print(f"Written: {output}  ({len(md)} chars, ~{len(md)//4} tokens)")
    if args.json:
        json_out = output.with_suffix(".json")
        json_out.write_text(json.dumps(master.to_dict(), indent=2))
        print(f"JSON:    {json_out}")


def cmd_list(args):
    store = ConversationStore(DATA_DIR)
    convs = store.list_conversations(project=args.project or None)
    if not convs:
        print("No conversations found.")
        return
    for c in convs:
        tags = f"  [{', '.join(c.projects)}]" if c.projects else ""
        extracted = " ✓" if (Path(DATA_DIR) / "contexts" / f"{c.id}.json").exists() else ""
        print(f"{c.date_last_modified.strftime('%Y-%m-%d')}  {c.title}{tags}{extracted}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = argparse.ArgumentParser(prog="context_manager", description="AI context manager")
    sub = root.add_subparsers(dest="command")

    # THE main command
    p_cg = sub.add_parser("to-chatgpt", help="Full pipeline: export zip/folder → clipboard")
    p_cg.add_argument("source", help="Claude export zip, folder, or single file")

    # Power-user commands
    p_upload = sub.add_parser("upload", help="Parse and store a conversation file")
    p_upload.add_argument("file")
    p_upload.add_argument("--tags", default="")

    p_extract = sub.add_parser("extract", help="Extract context via Claude API")
    p_extract.add_argument("id", nargs="?")
    p_extract.add_argument("--all", action="store_true")

    p_gen = sub.add_parser("generate", help="Generate master context markdown")
    p_gen.add_argument("--project", default="")
    p_gen.add_argument("--output", default="")
    p_gen.add_argument("--profile", default="")
    p_gen.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="List stored conversations")
    p_list.add_argument("--project", default="")

    p_serve = sub.add_parser("serve", help="Start FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    args = root.parse_args()

    if args.command == "to-chatgpt":
        cmd_to_chatgpt(args)
    elif args.command == "upload":
        cmd_upload(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "serve":
        import uvicorn
        uvicorn.run("context_manager.api:app", host=args.host, port=args.port, reload=True)
    else:
        root.print_help()


if __name__ == "__main__":
    main()
