"""從 Claude Code 回覆中提取 Context 估算與模型資訊"""
import re

from robot import i18n


def detect_brand(model: str) -> tuple[str, str, str]:
    """
    從 model name 偵測品牌、icon、顯示名稱。

    Returns:
        (brand_key, icon, display_name)
    """
    model_lower = model.lower()

    if "claude" in model_lower:
        brand = "claude"
        display_name = i18n.tr("footer.brand_claude")
        icon = "🧠"
    elif "gpt" in model_lower or "openai" in model_lower or "chatgpt" in model_lower:
        brand = "gpt"
        display_name = i18n.tr("footer.brand_gpt")
        icon = "🧠"
    elif "gemini" in model_lower:
        brand = "gemini"
        display_name = i18n.tr("footer.brand_gemini")
        icon = "🧠"
    elif "grok" in model_lower:
        brand = "grok"
        display_name = i18n.tr("footer.brand_grok")
        icon = "🧠"
    elif "deepseek" in model_lower:
        brand = "deepseek"
        display_name = i18n.tr("footer.brand_deepseek")
        icon = "🧠"
    elif "mistral" in model_lower:
        brand = "mistral"
        display_name = i18n.tr("footer.brand_mistral")
        icon = "🧠"
    else:
        brand = "unknown"
        display_name = i18n.tr("footer.brand_unknown")
        icon = "🧠"

    return brand, icon, display_name


# Model 名稱的正則表達式（支援各種格式）
_MODEL_PATTERN = r'([a-zA-Z][a-zA-Z0-9_-]+[-\.][a-zA-Z0-9_-]+)'


def clean_footer(text: str) -> str:
    """
    清理 Claude Code 回覆結尾的 `— model-name` 行。

    原始格式：
        📊 Context 估算：~16,000 / 200,000 tokens（約 8%）

        🧠 claude-opus-4-7 🧠
        — claude-opus-4-7

    清理後：
        📊 Context 估算：~16,000 / 200,000 tokens（約 8%）

        🧠 claude-opus-4-7 🧠
    """
    # 移除結尾的 `— model-name` 行（匹配各種破折號）
    text = re.sub(
        r'[^\w][-–—]?\s*' + _MODEL_PATTERN + r'\s*$',
        '',
        text,
        flags=re.IGNORECASE
    )
    return text


def parse_footer(text: str) -> dict | None:
    """
    解析 Claude Code 回覆結尾的 footer。

    標準格式：
        📊 Context 估算：~16,000 / 200,000 tokens（約 8%）
        — claude-opus-4-7

    Returns:
        dict with keys: context_used, context_limit, percentage, model
        None if 格式不符
    """
    text = text.strip()

    # Pattern 1: 完整格式（Context 估算 + Model）
    pattern1 = re.compile(
        r"📊\s*Context\s*估算[：:]\s*~?([\d,]+)\s*/\s*([\d,]+)\s*tokens[（(]約\s*(\d+)%?[）)]\s*\n[—\-]\s*(.+)",
        re.IGNORECASE
    )
    match = pattern1.search(text)
    if match:
        return {
            "context_used": match.group(1),
            "context_limit": match.group(2),
            "percentage": match.group(3),
            "model": match.group(4).strip()
        }

    # Pattern 2: 只有 Context 估算（沒有 Model 行）
    pattern2 = re.compile(
        r"📊\s*Context\s*估算[：:]\s*~?([\d,]+)\s*/\s*([\d,]+)\s*tokens[（(]約\s*(\d+)%?[）)]",
        re.IGNORECASE
    )
    match = pattern2.search(text)
    if match:
        return {
            "context_used": match.group(1),
            "context_limit": match.group(2),
            "percentage": match.group(3),
            "model": None
        }

    # Pattern 3: 只有 Model 行
    pattern3 = re.compile(r"[—\-]\s*(" + _MODEL_PATTERN + r")", re.IGNORECASE)
    match = pattern3.search(text)
    if match:
        return {
            "context_used": None,
            "context_limit": None,
            "percentage": None,
            "model": match.group(1).strip()
        }

    return None


def format_footer(result: dict) -> str:
    """
    格式化 footer 為漂亮的 icon 顯示（從 dict）。

    Input:
        {'context_used': '16,000', 'context_limit': '200,000',
         'percentage': '8', 'model': 'claude-opus-4-7'}

    Output:
        📊 Context 估算：~16,000 / 200,000 tokens（約 8%）

        🧠 claude-opus-4-7 🧠
    """
    context = result.get("context_used", "")
    limit = result.get("context_limit", "")
    pct = result.get("percentage", "")

    # 解析 model
    model = result.get("model")
    if model:
        _, icon, display_name = detect_brand(model)
        model_line = f"\n{icon} {display_name} {icon}"
    else:
        model_line = ""

    return f"📊 Context 估算：~{context} / {limit} tokens（約 {pct}%）{model_line}"


def format_footer_from_text(text: str) -> str:
    """
    從原始文字移除 footer 行。

    移除 `— model-name` 和 `🧠 model-name` 行。
    """
    # 移除 model footer 行（匹配多種破折號和 emoji）
    text = re.sub(
        r'\n?\s*[🧠]*\s*' + _MODEL_PATTERN + r'\s*\n?\s*[-–—]?\s*' + _MODEL_PATTERN + r'\s*$',
        '',
        text,
        flags=re.IGNORECASE
    )
    # 也移除單獨的 `🧠 model` 行
    text = re.sub(
        r'\n?\s*🧠\s*' + _MODEL_PATTERN + r'\s*$',
        '',
        text,
        flags=re.IGNORECASE
    )
    # 也移除原始的 `— model` 行
    text = re.sub(
        r'\n?\s*[-–—]\s*' + _MODEL_PATTERN + r'\s*$',
        '',
        text,
        flags=re.IGNORECASE
    )

    return text


if __name__ == "__main__":
    # 測試範例
    test_cases = [
        """✅ 專案[robot/feature] 處理完成 · 25s

你好！有什麼我可以幫你的嗎？

📊 Context 估算：~17,000 / 200,000 tokens（約 9%）

— claude-opus-4-7""",

        """✅ 專案[chat/master] 處理完成 · 80s

圖片已成功生成。

📊 Context 估算：~85,000 / 200,000 tokens（約 43%）

— gpt-5.3-codex""",
    ]

    print("=== Footer Parser Test ===\n")
    for i, text in enumerate(test_cases, 1):
        print(f"測試 {i}:")
        print("-" * 40)
        result = parse_footer(text)
        if result:
            print(f"  解析成功: model={result.get('model')}, context={result.get('context_used')}")
            formatted = format_footer(result)
            print(f"  格式化: {formatted}")
        else:
            print("  無法解析")
        print()