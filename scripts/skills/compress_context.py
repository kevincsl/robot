"""
compress-context skill: Compress conversation history using LLMLingua + coco index
to prevent token overflow errors in Claude/LLM API calls.

Usage:
  python scripts/skills/compress_context.py \
    --input files/conversation.json \
    --output files/conversation_compressed.json \
    --token-limit 200000 \
    --ratio 0.5
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import tiktoken
except ImportError:
    print("[compress-context] ERROR: tiktoken not installed. Run: pip install tiktoken")
    sys.exit(1)

COCO_INDEX_PATH = "files/coco_index.json"


def _default_token_limit() -> int:
    raw = os.getenv("COMPRESS_CONTEXT_TOKEN_LIMIT", "200000")
    try:
        return int(raw)
    except ValueError:
        print(f"[compress-context] Warning: invalid COMPRESS_CONTEXT_TOKEN_LIMIT={raw!r}; using 200000")
        return 200000


DEFAULT_TOKEN_LIMIT = _default_token_limit()
DEFAULT_RATIO = 0.5
TIKTOKEN_MODEL = "cl100k_base"


def count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding(TIKTOKEN_MODEL)
    return len(enc.encode(text))


def count_conversation_tokens(messages: list) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += count_tokens(block.get("text", ""))
        elif isinstance(content, str):
            total += count_tokens(content)
        total += 4  # per-message overhead
    return total


def load_conversation(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if raw.startswith("["):
        return json.loads(raw)
    # JSONL format
    messages = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            messages.append(json.loads(line))
    return messages


def load_coco_index(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updated_at": None, "facts": [], "summary": ""}


def save_coco_index(index: dict, path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    index["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"[compress-context] coco index saved: {path}")


def extract_facts_from_messages(messages: list) -> list:
    facts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = " ".join(parts)
        if not content or not isinstance(content, str):
            continue
        # Extract tool use events as facts
        if "tool_use" in str(msg):
            for block in (msg.get("content") if isinstance(msg.get("content"), list) else []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    facts.append({
                        "type": "tool_call",
                        "tool": block.get("name"),
                        "input_summary": str(block.get("input", ""))[:200],
                    })
        # Extract error messages as facts
        if "error" in content.lower() or "ERROR" in content:
            for line in content.splitlines():
                if "error" in line.lower() and len(line) > 10:
                    facts.append({"type": "error", "text": line.strip()[:300]})
                    break
        # Extract file paths mentioned
        import re
        paths = re.findall(r"[A-Za-z]:[\\\/][\w\\.\\\/\-_]+|\/[\w\\.\/\-_]{5,}", content)
        for p in paths[:3]:
            facts.append({"type": "file_path", "path": p})
    # Deduplicate
    seen = set()
    deduped = []
    for f in facts:
        key = json.dumps(f, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped[-50:]  # keep last 50 facts


def compress_with_llmlingua(messages: list, ratio: float, token_limit: int) -> list:
    try:
        from llmlingua import PromptCompressor
    except ImportError:
        print("[compress-context] ERROR: llmlingua not installed. Run: pip install llmlingua")
        sys.exit(1)

    print(f"[compress-context] Loading LLMLingua compressor (ratio={ratio})...")
    compressor = PromptCompressor(
        model_name="openai-community/gpt2",
        device_map="cpu",
        use_llmlingua2=False,
    )

    compressed_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if count_tokens(text) > 200:
                        try:
                            result = compressor.compress_prompt(
                                [text],
                                rate=ratio,
                                force_tokens=["\n"],
                            )
                            text = result["compressed_prompt"]
                        except Exception as e:
                            print(f"[compress-context] Warning: compression failed for block: {e}")
                    new_blocks.append({**block, "text": text})
                else:
                    new_blocks.append(block)
            compressed_messages.append({**msg, "content": new_blocks})
        elif isinstance(content, str) and count_tokens(content) > 200:
            try:
                result = compressor.compress_prompt(
                    [content],
                    rate=ratio,
                    force_tokens=["\n"],
                )
                content = result["compressed_prompt"]
            except Exception as e:
                print(f"[compress-context] Warning: compression failed for message: {e}")
            compressed_messages.append({**msg, "content": content})
        else:
            compressed_messages.append(msg)

    return compressed_messages


def truncate_oldest(messages: list, token_limit: int) -> list:
    """Fallback: drop oldest messages until under token limit."""
    while len(messages) > 2 and count_conversation_tokens(messages) > token_limit:
        # Always keep system message (index 0) if present
        if messages[0].get("role") == "system":
            messages = [messages[0]] + messages[2:]
        else:
            messages = messages[1:]
    return messages


def main():
    parser = argparse.ArgumentParser(description="Compress conversation context with LLMLingua + coco index")
    parser.add_argument("--input", required=True, help="Input conversation JSON or JSONL file")
    parser.add_argument("--output", required=True, help="Output compressed conversation JSON file")
    parser.add_argument("--token-limit", type=int, default=DEFAULT_TOKEN_LIMIT,
                        help=f"Token limit threshold (default: {DEFAULT_TOKEN_LIMIT})")
    parser.add_argument("--ratio", type=float, default=DEFAULT_RATIO,
                        help=f"LLMLingua compression ratio 0-1 (default: {DEFAULT_RATIO})")
    parser.add_argument("--coco-index", default=COCO_INDEX_PATH,
                        help=f"Path to coco index JSON (default: {COCO_INDEX_PATH})")
    parser.add_argument("--force", action="store_true",
                        help="Compress even if under token limit")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[compress-context] ERROR: Input file not found: {args.input}")
        sys.exit(1)

    print(f"[compress-context] Loading conversation: {args.input}")
    messages = load_conversation(args.input)
    print(f"[compress-context] Loaded {len(messages)} messages")

    token_count = count_conversation_tokens(messages)
    print(f"[compress-context] Token count: {token_count:,} / {args.token_limit:,}")

    if token_count <= args.token_limit and not args.force:
        print(f"[compress-context] Under limit — no compression needed.")
        # Still update coco index with any new facts
        coco = load_coco_index(args.coco_index)
        new_facts = extract_facts_from_messages(messages)
        coco["facts"] = (coco.get("facts", []) + new_facts)[-50:]
        coco["summary"] = f"Conversation has {len(messages)} messages, {token_count:,} tokens. Last checked: {time.strftime('%Y-%m-%dT%H:%M:%S')}"
        save_coco_index(coco, args.coco_index)
        # Copy input to output unchanged
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        print(f"[compress-context] Output written (unchanged): {args.output}")
        return

    # Update coco index before compressing
    coco = load_coco_index(args.coco_index)
    new_facts = extract_facts_from_messages(messages)
    coco["facts"] = (coco.get("facts", []) + new_facts)[-50:]
    coco["pre_compress_tokens"] = token_count
    coco["pre_compress_messages"] = len(messages)
    save_coco_index(coco, args.coco_index)

    print(f"[compress-context] Compressing with LLMLingua (ratio={args.ratio})...")
    compressed = compress_with_llmlingua(messages, args.ratio, args.token_limit)

    after_count = count_conversation_tokens(compressed)
    print(f"[compress-context] After LLMLingua: {after_count:,} tokens")

    if after_count > args.token_limit:
        print(f"[compress-context] Still over limit — applying truncation fallback...")
        compressed = truncate_oldest(compressed, args.token_limit)
        after_count = count_conversation_tokens(compressed)
        print(f"[compress-context] After truncation: {after_count:,} tokens ({len(compressed)} messages)")

    # Update coco index with post-compression stats
    coco["post_compress_tokens"] = after_count
    coco["post_compress_messages"] = len(compressed)
    coco["summary"] = (
        f"Compressed {token_count:,} → {after_count:,} tokens "
        f"({len(messages)} → {len(compressed)} messages). "
        f"Last compressed: {time.strftime('%Y-%m-%dT%H:%M:%S')}"
    )
    save_coco_index(coco, args.coco_index)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(compressed, f, ensure_ascii=False, indent=2)

    saved = token_count - after_count
    pct = (saved / token_count * 100) if token_count else 0
    print(f"[compress-context] Done. Saved {saved:,} tokens ({pct:.1f}%) → {args.output}")


if __name__ == "__main__":
    main()
