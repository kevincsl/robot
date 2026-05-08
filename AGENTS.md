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

Generate or edit raster images using AI. Three generation methods are available; ask the user which to use if they don't specify.

**Available methods:**

| Method | Command | Quality | Size | Key |
|--------|---------|---------|------|-----|
| **Pollinations.ai** | `python scripts/skills/pollinations_imagegen.py` | ⭐⭐⭐ | Up to 1024×1024 | None |
| **Gemini CLI** | `gemini -p "<prompt>" --yolo` | ⭐⭐⭐⭐ | 512×512 | OAuth login |

**When to use:** Photos, illustrations, textures, sprites, mockups, product shots, concept art, transparent cutouts.

**When NOT to use:** SVG/vector icon sets, simple shapes better done in CSS/HTML, editable source files already in repo.

**Workflow:**
1. Ask or infer which method to use (user preference → default to Pollinations.ai if none specified)
2. If **Pollinations.ai**: build structured prompt, run the script, send result to Telegram
3. If **Gemini CLI**: run `gemini -p "Generate <prompt>... Save the image to C:/Users/kevin/robot/files/<name>.png" --yolo`, then send to Telegram
4. Save outputs under `files/` or user-specified path

**Prompt spec (for Pollinations/Gemini CLI):**
```
Use case: <slug>
Asset type: <where used>
Primary request: <prompt>
Style/medium: <photo/illustration/3D>
Composition/framing: <wide/close/top-down>
Lighting/mood: <lighting + mood>
Constraints: <must keep/must avoid>
```

**Example prompts by method:**
```
# Pollinations (default)
python scripts/skills/pollinations_imagegen.py \
  --prompt "a fluffy orange cat in a cozy cafe, photorealistic" \
  --width 1024 --height 1024 \
  --style photorealistic \
  --out files/orange_cat.jpg

# Gemini CLI
gemini -p "Generate a 1024x1024 commercial-quality photorealistic image of a fluffy orange tabby cat sitting in a cozy Japanese-style cafe decorated with camellia flowers. Save the image to: C:/Users/kevin/robot/files/orange_cat_camellia.png" --yolo
```

**Transparent images (Pollinations only):**
1. Generate subject on flat `#00ff00` chroma-key background (`#ff00ff` for green subjects).
2. Run: `python scripts/skills/remove_chroma_key.py --input <src> --out <dst.png> --auto-key border --soft-matte --transparent-threshold 12 --opaque-threshold 220 --despill`
3. Validate alpha. Retry with `--edge-contract 1` if fringe remains.

**Use-case slugs:** photorealistic-natural, product-mockup, ui-mockup, infographic-diagram, scientific-educational, ads-marketing, productivity-visual, logo-brand, illustration-story, stylized-concept, historical-scene, text-localization, identity-preserve, precise-object-edit, lighting-weather, background-extraction, style-transfer, compositing, sketch-to-render

## pollinations-imagegen — AI Image Generation via Pollinations.ai

Generate images from text descriptions using the free Pollinations.ai API. **No API key required.** Preferred default for general use.

**Required info (ask if missing):**
- `--prompt` — 圖片內容描述（必填）
- `--width` / `--height` — 圖片尺寸，預設 1024×1024
- `--style` — 風格：`photorealistic` / `illustration` / `anime` / `oil-painting` / `watercolor` / `3d-render` / `pixel-art` / `sketch` / `cinematic`

**Workflow:**
1. Check if prompt, size, and style are provided
2. If any are missing, ask the user before proceeding
3. Run: `python scripts/skills/pollinations_imagegen.py --prompt "<desc>" --width <w> --height <h> --style <style> --out files/<name>.jpg`
4. Send result to Telegram: `python scripts/skills/send_tg_file.py --file files/<name>.jpg --caption "<desc>"`
5. Ask if user wants further changes (loop back to image-edit-loop if yes)

**Optional args:**
- `--model` — `flux` (default, balanced) / `turbo` (fast) / `flux-pro` (high quality)
- `--seed` — integer for reproducible results
- `--out` — output file path (default: `files/generated.jpg`)

**Example:**
```
python scripts/skills/pollinations_imagegen.py \
  --prompt "a futuristic city at night" \
  --width 1920 --height 1080 \
  --style cinematic \
  --out files/city.jpg
```

**Dependencies:** `pip install requests`

## gemini-imagegen — AI Image Generation via Gemini CLI

Generate images using the Gemini CLI with OAuth authentication. No API key needed — requires a logged-in Gemini CLI session.

**When to use:** User prefers Gemini CLI, or Pollinations fails. Trigger on "用 Gemini 生圖", "gemini generate image", etc.

**How it works:**
1. Run `gemini -p "<prompt>" --yolo` — Gemini generates an image and saves it to a path you specify in the prompt
2. Check the output file exists and is valid (first bytes should be PNG `89 50 4E` or JPEG `FF D8 FF`)
3. Send result to Telegram: `python scripts/skills/send_tg_file.py --file <path> --caption "<desc>"`

**Prompt template:**
```
Generate a <size> commercial-quality <style> image of <description>.
Save the image to: C:/Users/kevin/robot/files/<output_filename>.png
```

**Output file check:**
- PNG file starts with bytes `89 50 4E` — valid PNG
- JPEG file starts with bytes `FF D8 FF E1` — valid JPEG (often contains EXIF JSON metadata as text)
- If file is text/JSON (API error response), read it and report the error message

**Example:**
```bash
gemini -p "Generate a 1024x1024 commercial-quality photorealistic image of a fluffy orange tabby cat sitting in a cozy Japanese-style cafe decorated with camellia flowers. Save the image to: C:/Users/kevin/robot/files/orange_cat_camellia.png" --yolo
```

**Requirements:**
- Gemini CLI must be installed and OAuth session must be active (`gemini --version` works)
- Output directory must exist (`files/` must exist)

**Dependencies:** Gemini CLI with active OAuth login. No Python packages needed.

## videogen — AI Video Generation

Generate videos from text descriptions. Two pathways available — ask the user which to use if not specified.

**When to use:** User says "生成影片", "做一段影片", "generate video", "create video", etc.

**Available pathways:**

| 途徑 | 特色 | API Key |
|------|------|---------|
| **Pollinations.ai** | 免費、9 種模型、最長 120s | 不需要 |
| **Gemini CLI** | Google Veo 高品質、指定 prompt 自動存檔 | OAuth 登入 |

**Required info (ask if missing):**
- 影片描述 — 場景、動作、氛圍（必填）
- 途徑選擇 — Pollinations.ai 或 Gemini CLI（未指定則詢問）
- 畫面比例 — 16:9 / 9:16 / 1:1（Pollinations 需指定尺寸；Gemini 可在 prompt 中描述）
- 影片長度 — 秒數（選填）

**Workflow:**
1. Confirm prompt, pathway, size/ratio with user — ask for anything missing
2. **If Pollinations.ai:**
   ```
   python scripts/skills/pollinations_videogen.py \
     --prompt "<desc>" --model <model> \
     --width <w> --height <h> --duration <s> \
     --out files/<name>.mp4
   ```
3. **If Gemini CLI:**
   ```
   gemini -p "Generate a <ratio> video of <desc>. Duration: <s> seconds. Save to: C:/Users/kevin/robot/files/<name>.mp4" --yolo
   ```
4. Send result: `python scripts/skills/send_tg_file.py --file files/<name>.mp4 --caption "<desc>"`
5. Ask if user wants to generate another version

**Pollinations models:**

| Model | 特色 |
|-------|------|
| `seedance` | 預設，速度與品質平衡 |
| `seedance-pro` | 高品質 |
| `wan` / `wan-fast` | 通用型 |
| `nova-reel` | 最長支援 120 秒 |
| `ltx-2` | 輕量快速 |
| `veo` | Google Veo |
| `grok-video-pro` | Grok 高品質 |
| `p-video` | 直向影片 |

**Pollinations optional args:**
- `--model` — 見上方模型表（default: `seedance`）
- `--duration` — 影片秒數（`nova-reel` 最長 120s）
- `--seed` — integer for reproducible results
- `--key` — Pollinations API key（或設環境變數 `POLLINATIONS_API_KEY`）
- `--out` — output file path（default: `files/generated_video.mp4`）

**Note:** 影片生成通常需要 1–3 分鐘，請耐心等待。

**Dependencies:** `pip install requests` (Pollinations); Gemini CLI with active OAuth login (Gemini)

## image-edit-loop — Interactive Image Editing Loop

Edit images iteratively, sending each result to Telegram for review.

**When to use:** User provides an image and wants one or more edits (remove objects, adjust colors, crop, blur, etc.) in a back-and-forth loop until satisfied.

**Workflow:**
1. User provides image path → copy to temp working directory
2. Ask: "想做什麼修改？"
3. Perform the modification using PIL / OpenCV / numpy
4. Send result via Telegram: `python scripts/skills/send_tg_file.py --file <path> --caption "修改完成，還要繼續調整嗎？"`
5. Ask: "這個檔案還要進行什麼樣的修改？"
6. Repeat steps 3–5 until user says "OK" or changes topic

**State between edits:**
- `INPUT_IMAGE` — original uploaded image (never modified)
- `LAST_OUTPUT` — latest result (base for next edit)

**Available modifications (examples):**
- `remove_object x1 y1 x2 y2` — remove object at pixel region using clone-paste fill
- `blur_region x1 y1 x2 y2` — Gaussian blur the region
- `brightness delta` — adjust brightness (±1–3)
- `crop x1 y1 x2 y2` — crop to region
- `rotate degrees` — rotate image
- `desaturate` — convert to grayscale

**Dependencies:** `pip install pillow opencv-python numpy`

## send-tg-file — Send File to Telegram

**Usage:** `python scripts/skills/send_tg_file.py --file <path> --caption "<text>"`

- Images (.png/.jpg/.jpeg/.webp) → `sendPhoto`; others → `sendDocument`.
- Reads `TELEAPP_TOKEN` and `TELEAPP_ALLOWED_USER_ID` from `.env`.
- Use `--env <path>` for alternate .env file.
- Never print or expose token values.

**Dependencies:** `pip install requests python-dotenv`
