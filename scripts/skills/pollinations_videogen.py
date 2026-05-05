"""
pollinations-videogen skill: Generate videos via Pollinations.ai API.

Usage:
  python scripts/skills/pollinations_videogen.py \
    --prompt "a cat walking on the moon" \
    --model seedance \
    --duration 5 \
    --width 1280 --height 720 \
    --out files/output.mp4

Missing required args trigger interactive prompts.
"""

import argparse
import os
import sys
import urllib.parse
import requests

VALID_MODELS = [
    "seedance",       # balanced, fast
    "seedance-pro",   # high quality
    "wan",            # general purpose
    "wan-fast",       # faster wan
    "nova-reel",      # up to 120s
    "ltx-2",          # lightweight
    "veo",            # Google Veo
    "grok-video-pro", # Grok
    "p-video",        # portrait video
]

VALID_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"]

DEFAULT_MODEL = "seedance"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
API_BASE = "https://gen.pollinations.ai/video"


def ask(question, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer if answer else default


def build_url(prompt, model, width, height, duration, seed, api_key):
    encoded = urllib.parse.quote(prompt)
    params = f"?model={model}&width={width}&height={height}"
    if duration:
        params += f"&duration={duration}"
    if seed is not None:
        params += f"&seed={seed}"
    if api_key:
        params += f"&key={api_key}"
        params += "&nologo=true"
    return f"{API_BASE}/{encoded}{params}"


def generate(prompt, model, width, height, duration, out_path, seed=None, api_key=None):
    url = build_url(prompt, model, width, height, duration, seed, api_key)
    print(f"[pollinations-videogen] Generating video (this may take 1-3 minutes)...")
    print(f"[pollinations-videogen] Model: {model} | Size: {width}x{height}" + (f" | Duration: {duration}s" if duration else ""))

    r = requests.get(url, timeout=300)
    r.raise_for_status()

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)

    size_mb = len(r.content) / (1024 * 1024)
    print(f"[pollinations-videogen] Saved: {out_path} ({size_mb:.1f} MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate video via Pollinations.ai")
    parser.add_argument("--prompt", help="Video description / scene to generate")
    parser.add_argument("--model", help=f"Model: {', '.join(VALID_MODELS)}")
    parser.add_argument("--width", type=int, help="Width in pixels (default 1280)")
    parser.add_argument("--height", type=int, help="Height in pixels (default 720)")
    parser.add_argument("--duration", type=int, help="Duration in seconds (model-dependent)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    parser.add_argument("--key", help="Pollinations API key (optional, for higher limits)")
    parser.add_argument("--out", help="Output file path (default: files/generated_video.mp4)")
    args = parser.parse_args()

    # --- Collect missing info interactively ---
    prompt = args.prompt
    if not prompt:
        print("[pollinations-videogen] 缺少影片描述，請回答以下問題：")
        prompt = ask("請描述你想要的影片內容（場景、動作、氛圍）")
        if not prompt:
            print("錯誤：影片描述不能為空。")
            sys.exit(1)

    model = args.model
    if not model:
        model_list = " / ".join(VALID_MODELS)
        model = ask(f"選擇模型（{model_list}）", default=DEFAULT_MODEL)
        if model not in VALID_MODELS:
            print(f"警告：未知模型 '{model}'，使用預設 {DEFAULT_MODEL}")
            model = DEFAULT_MODEL

    width = args.width
    height = args.height
    if not width or not height:
        ratio = ask("畫面比例（16:9 / 9:16 / 1:1）", default="16:9")
        if ratio == "16:9":
            width, height = width or 1280, height or 720
        elif ratio == "9:16":
            width, height = width or 720, height or 1280
        elif ratio == "1:1":
            width, height = width or 1024, height or 1024
        else:
            width = width or DEFAULT_WIDTH
            height = height or DEFAULT_HEIGHT

    duration = args.duration
    if not duration:
        dur_str = ask("影片長度（秒，留空使用模型預設）", default="")
        if dur_str:
            try:
                duration = int(dur_str)
            except ValueError:
                duration = None

    out_path = args.out or "files/generated_video.mp4"
    api_key = args.key or os.environ.get("POLLINATIONS_API_KEY")

    generate(prompt, model, width, height, duration, out_path, args.seed, api_key)


if __name__ == "__main__":
    main()
