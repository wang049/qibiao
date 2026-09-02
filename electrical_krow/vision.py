"""扫描页图：只打指定场所识别服务，禁止公网。看图结果当原文，不拿 OCR 模型出 JSON 核对表。"""
from __future__ import annotations

import io
from typing import Any

_TEXT_CHAT = {
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.2",
    "zhipu/glm-5.2",
}


def is_text_chat_model(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in _TEXT_CHAT:
        return True
    if n.endswith("/glm-5.2"):
        return True
    return False


def message_has_image(content: object) -> bool:
    if isinstance(content, dict):
        kind = str(content.get("type") or "").lower()
        if kind in {"image_url", "image"} or "image_url" in content:
            return True
        return message_has_image(content.get("content"))
    if isinstance(content, list):
        return any(message_has_image(item) for item in content)
    return False


def pick_vision_model(names: list[str], preferred: str = "") -> str:
    """选出看图/表格识别模型。deepseek-v4-pro、GLM-5.2 文本版不用于页图。"""
    pref = (preferred or "").strip()
    if pref and not is_text_chat_model(pref):
        if not names or pref in names:
            return pref
    ranked: list[tuple[int, str]] = []
    for name in names:
        raw = (name or "").strip()
        if not raw or is_text_chat_model(raw):
            continue
        low = raw.lower()
        if "ocr-table" in low or "ocr_table" in low:
            ranked.append((0, raw))
        elif any(
            token in low
            for token in (
                "-vl",
                "vl-",
                "vision",
                "4v",
                "internvl",
                "qwen-vl",
                "qwen2-vl",
                "qwen2.5-vl",
            )
        ):
            ranked.append((1, raw))
        elif "ocr" in low:
            ranked.append((2, raw))
    ranked.sort()
    return ranked[0][1] if ranked else ""


def sample_probe_png() -> bytes:
    """联调用的合成页，不是规格书。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 48), "HVDC bus voltage 380 V", fill=(20, 20, 20))
    draw.text((24, 96), "Min level for limited performance", fill=(20, 20, 20))
    draw.text((24, 144), "performance limit 380", fill=(20, 20, 20))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def image_chat_messages(png_or_jpeg: bytes, mime: str, prompt: str) -> list[dict[str, Any]]:
    import base64

    b64 = base64.b64encode(png_or_jpeg).decode("ascii")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
            ],
        }
    ]
