# Agent Rules

- Do not modify any files under `teleapp/` or `_vendor_teleapp/` unless the user explicitly approves in the current conversation.
- If a change there is necessary, ask for confirmation first and wait for approval before editing.
- When teleapp changes are approved, keep both copies in sync: `C:\Users\kevin\codex\robot\teleapp` and `C:\Users\kevin\teleapp\teleapp` (and corresponding `_vendor_teleapp` mirrors when applicable).
- Never modify `.env` unless the user explicitly confirms first.
- Do not treat stopping teleapp as a successful restart. Assume teleapp may not be restartable unless explicitly verified after launch.
- Only modify files inside the project root directory (including all subdirectories). Any file changes outside the project root require explicit user confirmation first.
- For document-analysis tasks, prefer `markitdown` first:
  - If user provides `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xls`, `.html`, `.htm`, or similar office/web documents, convert to Markdown before summarizing, searching, comparing, or extracting structured notes.
  - If user explicitly asks for direct raw-file handling instead of conversion, follow user instruction.
- For email delivery tasks, use local sendmail project by default:
  - Preferred command path: `python C:\Users\kevin\codex\sendmail\sendmail.py ...`
  - Trigger when user asks to "寄信", "寄到信箱", "email", or "send".
  - If recipient, subject, or body is missing, ask for missing fields first.
  - Attach generated Markdown report files by default when available, unless user says not to attach.

---

# Shared Skills

All agents in this project (Codex, Claude Code, Gemini CLI, Windsurf) share the skills below.
Scripts live in `scripts/skills/`. This is the single source of truth — do not duplicate these definitions elsewhere.

## chromeontg — Headless Chrome + Telegram

Drive headless Chrome and send screenshots to Telegram for remote, step-by-step web operation.

**When to use:** User wants to open a URL, take screenshots, receive instructions via Telegram, execute browser actions, and send updated screenshots back.

**Workflow:**
1. Confirm target URL and first action list from the user.
2. Ensure output folder exists at `files/`.
3. Write a JSON step file. Supported actions:
   - `{"action":"goto","url":"https://..."}`
   - `{"action":"click","selector":"css/xpath/text selector"}`
   - `{"action":"type","selector":"...","text":"...","clear":true}`
   - `{"action":"press","key":"Enter"}`
   - `{"action":"select","selector":"...","value":"option_value"}`
   - `{"action":"wait","ms":1500}`
   - `{"action":"screenshot","name":"step-xx.png","full_page":true}`
4. Run: `python scripts/skills/chrome_tg_runner.py --steps <steps.json> --out-dir files`
5. Send screenshots: `python scripts/skills/send_tg_file.py --file <path> --caption "<desc>"`
6. Wait for next instruction, repeat until done.

**Guardrails:**
- Screenshots only under `files/`.
- Uses `.env` values `TELEAPP_TOKEN` and `TELEAPP_ALLOWED_USER_ID`.
- Never print token values.
- On selector failure, capture a debug screenshot and send to Telegram before retrying.

**Dependencies:** `pip install playwright requests python-dotenv && python -m playwright install chromium`

## imagegen — AI Image Generation / Editing

Generate or edit raster images using AI. Supports transparent-background cutouts via chroma-key removal.

**When to use:** Photos, illustrations, textures, sprites, mockups, product shots, concept art, transparent cutouts.

**When NOT to use:** SVG/vector icon sets, simple shapes better done in CSS/HTML, editable source files already in repo.

**Workflow:**
1. Decide intent: **generate** (new) or **edit** (modify existing).
2. Augment user prompt into structured spec:
   ```
   Use case: <slug>
   Asset type: <where used>
   Primary request: <prompt>
   Style/medium: <photo/illustration/3D>
   Composition/framing: <wide/close/top-down>
   Lighting/mood: <lighting + mood>
   Constraints: <must keep/must avoid>
   ```
3. Use built-in image generation tool by default.
4. Save outputs under `files/` or user-specified path.

**Transparent images:**
1. Generate subject on flat `#00ff00` chroma-key background (`#ff00ff` for green subjects).
2. Run: `python scripts/skills/remove_chroma_key.py --input <src> --out <dst.png> --auto-key border --soft-matte --transparent-threshold 12 --opaque-threshold 220 --despill`
3. Validate alpha. Retry with `--edge-contract 1` if fringe remains.

**Use-case slugs:** photorealistic-natural, product-mockup, ui-mockup, infographic-diagram, scientific-educational, ads-marketing, productivity-visual, logo-brand, illustration-story, stylized-concept, historical-scene, text-localization, identity-preserve, precise-object-edit, lighting-weather, background-extraction, style-transfer, compositing, sketch-to-render

**Dependencies:** `pip install pillow`

## send-tg-file — Send File to Telegram

Send any file to Telegram via bot API.

**Usage:** `python scripts/skills/send_tg_file.py --file <path> --caption "<text>"`

- Images (.png/.jpg/.jpeg/.webp) → `sendPhoto`; others → `sendDocument`.
- Reads `TELEAPP_TOKEN` and `TELEAPP_ALLOWED_USER_ID` from `.env`.
- Use `--env <path>` for alternate .env file.
- Never print or expose token values.

**Dependencies:** `pip install requests python-dotenv`
