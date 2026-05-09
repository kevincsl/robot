---
description: Compress conversation context with LLMLingua and optional token-limit override
---

Full docs: see `AGENTS.md` -> **compress-context** section.

1. Prepare input conversation file (JSON or JSONL).
2. Run with default token budget (200000) or set env override.
3. Write compressed output and use it for the next API call.

Default run (uses `COMPRESS_CONTEXT_TOKEN_LIMIT` fallback = 200000):
```powershell
python scripts/skills/compress_context.py --input files/conversation.json --output files/conversation_compressed.json --ratio 0.5
```

Override default token budget for this session:
```powershell
$env:COMPRESS_CONTEXT_TOKEN_LIMIT = 400000
python scripts/skills/compress_context.py --input files/conversation.json --output files/conversation_compressed.json --ratio 0.5
```
