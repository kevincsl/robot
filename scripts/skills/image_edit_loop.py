"""
image-edit-loop skill: interactive image editing loop via Telegram.

Workflow:
1. User provides an image → copy to accessible temp path
2. Ask user what modification they want
3. Perform the modification using PIL/OpenCV/numpy
4. Send result to Telegram
5. Ask what else to do → repeat until user says "OK" or changes topic
"""

import argparse
import sys
import os
import shutil
import tempfile

from PIL import Image
import numpy as np
import cv2

TEMP_WORK = os.path.join(tempfile.gettempdir(), "img_edit_work")
os.makedirs(TEMP_WORK, exist_ok=True)

INPUT_IMAGE = None  # path to the current working image
LAST_OUTPUT = None  # path to the last result (for next iteration base)


def copy_to_work(src_path):
    """Copy user-provided image to working directory."""
    global INPUT_IMAGE, LAST_OUTPUT
    dst = os.path.join(TEMP_WORK, "original.jpg")
    shutil.copy2(src_path, dst)
    INPUT_IMAGE = dst
    LAST_OUTPUT = dst
    return dst


def get_working_image():
    return LAST_OUTPUT or INPUT_IMAGE


def save_result(arr, filename="result.jpg"):
    path = os.path.join(TEMP_WORK, filename)
    Image.fromarray(arr).save(path, quality=95)
    global LAST_OUTPUT
    LAST_OUTPUT = path
    return path


def send_to_tg(file_path, caption=""):
    import subprocess
    cmd = [
        sys.executable, os.path.join(os.path.dirname(__file__), "send_tg_file.py"),
        "--file", file_path
    ]
    if caption:
        cmd += ["--caption", caption]
    subprocess.run(cmd, check=True)


# ---- modification helpers ----

def remove_region(img_arr, x1, y1, x2, y2):
    """Fill region by sampling left side, flipping, resizing."""
    h, w = y2 - y1, x2 - x1
    sample_x1 = max(0, x1 - w)
    sample = img_arr[y1:y2, sample_x1:x1]
    sample = cv2.flip(sample, 1)
    patch = cv2.resize(sample, (w, h))
    arr = img_arr.copy()
    arr[y1:y2, x1:x2] = patch
    return arr


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="image-edit-loop")
    parser.add_argument("--file", help="Initial image path provided by user")
    args = parser.parse_args()

    if args.file:
        path = copy_to_work(args.file)
        print(f"[image-edit-loop] Image loaded: {path}")
        # Signal to Claude: image is loaded, ask user what to do
        print("[ASK] 圖片已載入，請告訴我想做什麼修改？")
    else:
        print("[image-edit-loop] No initial file provided. Waiting for image input.")