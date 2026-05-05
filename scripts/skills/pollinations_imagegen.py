"""
pollinations-imagegen skill: Generate images via Pollinations.ai API.

Usage:
  python scripts/skills/pollinations_imagegen.py \
    --prompt "a cat on the moon" \
    --width 1024 --height 1024 \
    --style "photorealistic" \
    --out files/output.jpg

Missing args trigger interactive prompts.
"""

import argparse
import os
import sys
import urllib.parse
import requests

VALID_STYLES = [
    "photorealistic", "illustration", "anime", "oil-painting",
    "watercolor", "3d-render", "pixel-art", "sketch", "cinematic",
]

MODELS = {
    "default": "flux",
    "fast": "turbo",
    "quality": "flux-pro",
}

DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_MODEL = "flux"
API_BASE = "https://image.pollinations.ai/prompt"


def ask(question, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer if answer else default


def build_url(prompt, width, height, model, seed=None, nologo=True):
    encoded = urllib.parse.quote(prompt)
    params = f"?width={width}&height={height}&model={model}&nologo={'true' if nologo else 'false'}"
    if seed is not None:
        params += f"&seed={seed}"
    return f"{API_BASE}/{encoded}{params}"


def generate(prompt, width, height, model, out_path, seed=None):
    url = build_url(prompt, width, height, model, seed)
    print(f"[pollinations-imagegen] Generating: {url[:100]}...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    print(f"[pollinations-imagegen] Saved: {out_path} ({len(r.content)//1024} KB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Generate image via Pollinations.ai")
    parser.add_argument("--prompt", help="Image description")
    parser.add_argument("--width", type=int, help="Width in pixels")
    parser.add_argument("--height", type=int, help="Height in pixels")
    parser.add_argument("--style", help=f"Style hint, e.g.: {', '.join(VALID_STYLES)}")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model: flux, turbo, flux-pro")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    parser.add_argument("--out", help="Output file path (default: files/generated.jpg)")
    args = parser.parse_args()

    # --- Collect missing info interactively ---
    prompt = args.prompt
    if not prompt:
        print("[pollinations-imagegen] 缺少圖片描述，請回答以下問題：")
        prompt = ask("請描述你想要的圖片內容")
        if not prompt:
            print("錯誤：圖片描述不能為空。")
            sys.exit(1)

    style = args.style
    if not style:
        style_list = " / ".join(VALID_STYLES)
        style = ask(f"圖片風格（{style_list}）", default="photorealistic")

    # Append style to prompt if provided
    if style and style not in prompt:
        prompt = f"{prompt}, {style} style"

    width = args.width
    if not width:
        w_str = ask("圖片寬度（pixels）", default=str(DEFAULT_WIDTH))
        try:
            width = int(w_str)
        except ValueError:
            width = DEFAULT_WIDTH

    height = args.height
    if not height:
        h_str = ask("圖片高度（pixels）", default=str(DEFAULT_HEIGHT))
        try:
            height = int(h_str)
        except ValueError:
            height = DEFAULT_HEIGHT

    out_path = args.out or "files/generated.jpg"
    model = args.model or DEFAULT_MODEL
    seed = args.seed

    generate(prompt, width, height, model, out_path, seed)


if __name__ == "__main__":
    main()
