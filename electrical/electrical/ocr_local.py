"""本机 OCR：把 PDF 里抽不出字的矢量表格渲成图再认字。文件不出公网。"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

from electrical.doc_kind import PARAM_RE, page_text_kind
from electrical.progress import checkpoint, report

MAX_OCR_PAGES = int(os.environ.get("SPEC_SHEET_MAX_OCR_PAGES", "40"))
MAX_SCAN_OCR_PAGES = int(os.environ.get("SPEC_SHEET_MAX_SCAN_OCR_PAGES", "120"))
_RAPID_GOOD = 85
_RAPID_LOCK = threading.Lock()
_SWIFT_SRC = Path(__file__).resolve().parent.parent / "scripts" / "ocr_page.swift"
_BIN = Path(__file__).resolve().parent.parent / ".ocr_bin" / "ocr_page"
_VISION_FAIL_LOGGED = False


def ocr_available() -> bool:
    if _page_ocr_ready():
        return True
    if _rapidocr_engine() is not None:
        return True
    if _vision_bin() is not None:
        return True
    if _tesseract_bin() is not None:
        return True
    return _page_vision_ready()


def _ocr_workers() -> int:
    try:
        n = int(os.environ.get("SPEC_SHEET_OCR_PARALLEL", "4"))
    except ValueError:
        n = 4
    return max(1, min(6, n))


@lru_cache(maxsize=1)
def _apple_silicon() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        raw = subprocess.check_output(
            ["sysctl", "-n", "hw.optional.arm64"],
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        return raw.strip() == b"1"
    except (OSError, subprocess.SubprocessError):
        return False


def _helper_usable(path: Path) -> bool:
    """Apple 芯片上必须用 arm64 助手。x86 版会跑完每一页但 Vision 一个字都认不出。"""
    if not path.is_file() or path.stat().st_size < 20_000:
        return False
    if not _apple_silicon():
        return True
    try:
        info = subprocess.check_output(
            ["file", "-b", str(path)],
            timeout=2,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return path.stat().st_size >= 70_000
    return "arm64" in info


def _tesseract_bin() -> str | None:
    from shutil import which

    found = which("tesseract")
    if found:
        return found
    if sys.platform != "win32":
        return None
    roots = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")),
    ]
    candidates = []
    for root in roots:
        if not str(root):
            continue
        candidates.append(root / "Tesseract-OCR" / "tesseract.exe")
        candidates.append(root / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


@lru_cache(maxsize=1)
def _tesseract_langs(tess: str) -> str:
    try:
        raw = subprocess.check_output(
            [tess, "--list-langs"],
            timeout=8,
            stderr=subprocess.STDOUT,
        )
        blob = raw.decode("utf-8", errors="replace").lower()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        blob = ""
    langs: list[str] = []
    if "chi_sim" in blob:
        langs.append("chi_sim")
    if "eng" in blob:
        langs.append("eng")
    if langs:
        return "+".join(langs)
    return "chi_sim+eng"


def _ocr_text_score(text: str) -> int:
    """参数单位、汉字越多越好；# 乱码扣分。"""
    blob = text or ""
    param = len(PARAM_RE.findall(blob))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", blob))
    alnum = len(re.findall(r"[A-Za-z0-9]", blob))
    junk = len(re.findall(r"[#�]{1,}", blob))
    return param * 50 + cjk + alnum // 3 - junk * 8


def _page_vision_enabled() -> bool:
    return os.environ.get("SPEC_SHEET_PAGE_VISION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _page_vision_model() -> str:
    return (os.environ.get("SPEC_SHEET_VISION_MODEL") or "").strip()


def _llm_origin_loopback() -> str:
    """页图只打本机网关。禁止 electrical 直连场所或公网。"""
    raw = (os.environ.get("SPEC_SHEET_LLM_URL") or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/v1"):
        raw = raw[:-3]
    from urllib.parse import urlparse
    import ipaddress

    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return f"{parsed.scheme}://{parsed.netloc}"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if ip.is_loopback or (getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback):
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _page_ocr_enabled() -> bool:
    return os.environ.get("SPEC_SHEET_PAGE_OCR", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _page_ocr_task() -> str:
    raw = (os.environ.get("SPEC_SHEET_OCR_TASK") or "table").strip().lower()
    return raw if raw in {"table", "ocr"} else "table"


def _page_ocr_ready() -> bool:
    return _page_ocr_enabled() and bool(_llm_origin_loopback())


def _compress_page_jpeg(image_path: Path, max_side: int = 1600) -> tuple[bytes, str]:
    from PIL import Image

    im = Image.open(image_path)
    if im.mode != "RGB":
        im = im.convert("RGB")
    width, height = im.size
    long_side = max(width, height, 1)
    if long_side > max_side:
        scale = max_side / long_side
        im = im.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    import io

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return buf.getvalue(), "image/jpeg"


def _run_krow_ocr(image_path: Path) -> str:
    """经本机网关打当前识别服务的 /v1/ocr（SDK OCR）。"""
    if not _page_ocr_ready():
        return ""
    origin = _llm_origin_loopback()
    if not origin:
        return ""
    try:
        jpeg, mime = _compress_page_jpeg(image_path)
    except Exception:
        return ""
    import base64

    import httpx

    b64 = base64.b64encode(jpeg).decode("ascii")
    timeout = float(os.environ.get("SPEC_SHEET_OCR_TIMEOUT", "90"))
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(
                f"{origin}/v1/ocr",
                headers={
                    "Authorization": "Bearer local",
                    "Content-Type": "application/json",
                },
                json={
                    "task": _page_ocr_task(),
                    "image": f"data:{mime};base64,{b64}",
                },
            )
    except httpx.HTTPError:
        return ""
    if resp.status_code >= 400:
        return ""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    text = str(body.get("text") or "").strip()
    if not text:
        pages = body.get("pages") or []
        parts: list[str] = []
        for page in pages:
            if isinstance(page, dict):
                blob = str(page.get("text") or "").strip()
                if blob:
                    parts.append(blob)
        text = "\n".join(parts)
    return _cleanup_ocr_text(text)


def _page_vision_ready() -> bool:
    return (
        _page_vision_enabled()
        and bool(_page_vision_model())
        and bool(_llm_origin_loopback())
    )


def _run_site_page_vision(image_path: Path) -> str:
    """低分页经本机网关送指定场所看图。结果当原文，不用 OCR 模型出 JSON。"""
    if not _page_vision_ready():
        return ""
    origin = _llm_origin_loopback()
    model = _page_vision_model()
    if not origin or not model:
        return ""
    try:
        jpeg, mime = _compress_page_jpeg(image_path)
    except Exception:
        return ""
    import base64

    import httpx

    b64 = base64.b64encode(jpeg).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "把这张规格书页还原成纯文本。按原行列排布，中英对照用空格分开。"
                            "不要编造数字、单位或标准号。只输出原文。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    timeout = float(os.environ.get("SPEC_SHEET_VISION_TIMEOUT", "90"))
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(
                f"{origin}/v1/chat/completions",
                headers={
                    "Authorization": "Bearer local",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError:
        return ""
    if resp.status_code >= 400:
        return ""
    try:
        body = resp.json()
        text = body["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
    return _cleanup_ocr_text(str(text).strip())


@lru_cache(maxsize=1)
def _rapidocr_engine():
    """PP-OCRv4/v5 ONNX，中英对照表比系统 Vision / Tesseract 稳。缺包则跳过。"""
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return None
    import logging

    logging.getLogger("RapidOCR").setLevel(logging.ERROR)
    try:
        return RapidOCR()
    except Exception:
        return None


def _run_rapidocr(image_path: Path) -> str:
    engine = _rapidocr_engine()
    if engine is None:
        return ""
    try:
        with _RAPID_LOCK:
            result = engine(str(image_path))
    except Exception:
        return ""
    if result is None or result.txts is None or result.boxes is None:
        return ""
    return _cleanup_ocr_text(_boxes_to_layout_text(result.boxes, result.txts))


def _box_props(box) -> dict[str, float]:
    xs = [float(pt[0]) for pt in box]
    ys = [float(pt[1]) for pt in box]
    top, bottom, left, right = min(ys), max(ys), min(xs), max(xs)
    return {
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
        "height": max(1.0, bottom - top),
        "center_y": (top + bottom) / 2,
    }


def _same_ocr_line(current: dict[str, float], line: dict[str, float]) -> bool:
    overlap = max(0.0, min(line["bottom"], current["bottom"]) - max(line["top"], current["top"]))
    min_h = max(1.0, min(current["height"], line["height"]))
    if overlap / min_h > 0.5:
        return True
    return abs(current["center_y"] - line["center_y"]) < min_h * 0.35


def _boxes_to_layout_text(boxes, txts) -> str:
    """按检测框还原行列：同一行单元格用空格分开，避免中英粘成一词。"""
    items: list[dict] = []
    if boxes is None or txts is None:
        return ""
    for box, raw in zip(boxes, txts):
        text = str(raw or "").strip()
        if not text:
            continue
        items.append({"text": text, "props": _box_props(box)})
    if not items:
        return ""
    items.sort(key=lambda item: (item["props"]["center_y"], item["props"]["left"]))
    lines: list[dict] = []
    for item in items:
        props = item["props"]
        if lines and _same_ocr_line(props, lines[-1]["props"]):
            line = lines[-1]
            line["items"].append(item)
            merged = line["props"]
            merged["top"] = min(merged["top"], props["top"])
            merged["bottom"] = max(merged["bottom"], props["bottom"])
            merged["left"] = min(merged["left"], props["left"])
            merged["right"] = max(merged["right"], props["right"])
            merged["height"] = max(1.0, merged["bottom"] - merged["top"])
            merged["center_y"] = (merged["top"] + merged["bottom"]) / 2
            continue
        lines.append({"items": [item], "props": dict(props)})
    out: list[str] = []
    for line in lines:
        line["items"].sort(key=lambda item: item["props"]["left"])
        out.append("  ".join(item["text"] for item in line["items"]))
    return "\n".join(out)


def _keep_ocr_page(text: str) -> bool:
    blob = (text or "").strip()
    if len(blob) < 24:
        return False
    if page_text_kind(blob) == "toc" and len(PARAM_RE.findall(blob)) < 2:
        return False
    return True


def _page_zoom(page) -> float:
    rect = page.rect
    short = min(float(rect.width), float(rect.height), 1.0)
    zoom = 1600.0 / short
    return max(1.8, min(2.8, zoom))


def _prepare_ocr_image(image_path: Path) -> Path:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return image_path
    try:
        im = Image.open(image_path)
        im = ImageOps.grayscale(im)
        width, height = im.size
        min_side = min(width, height)
        if min_side < 1400:
            scale = min(2.4, 1400 / max(min_side, 1))
            im = im.resize(
                (int(width * scale), int(height * scale)),
                Image.Resampling.LANCZOS,
            )
        im = ImageOps.autocontrast(im, cutoff=1)
        im = im.filter(ImageFilter.SHARPEN)
        out = image_path.with_name(image_path.stem + "_prep.png")
        im.save(out)
        return out
    except OSError:
        return image_path


def _run_tesseract(tess: str, image: Path, langs: str, psm: str) -> str:
    raw = subprocess.check_output(
        [
            tess,
            str(image),
            "stdout",
            "-l",
            langs,
            "--oem",
            "3",
            "--psm",
            psm,
            "--dpi",
            "300",
        ],
        timeout=90,
        stderr=subprocess.DEVNULL,
    )
    return raw.decode("utf-8", errors="replace").strip()


def _swiftc_bin() -> str:
    swiftc = "/usr/bin/swiftc"
    if Path(swiftc).is_file():
        return swiftc
    from shutil import which

    return which("swiftc") or "swiftc"


def _vision_compile_commands(staging: Path) -> list[list[str]]:
    swiftc = _swiftc_bin()
    frameworks = ["-framework", "Vision", "-framework", "AppKit"]
    src = str(_SWIFT_SRC)
    out = str(staging)
    cmds = [[swiftc, "-O", "-o", out, src, *frameworks]]
    if _apple_silicon():
        cmds.insert(
            0,
            [swiftc, "-target", "arm64-apple-macosx13.0", "-O", "-o", out, src, *frameworks],
        )
    return cmds


def _vision_bin() -> Path | None:
    if sys.platform != "darwin" or not _SWIFT_SRC.is_file():
        return None
    if (
        _helper_usable(_BIN)
        and _BIN.stat().st_mtime >= _SWIFT_SRC.stat().st_mtime
    ):
        return _BIN
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    staging = _BIN.with_name(_BIN.name + ".building")
    staging.unlink(missing_ok=True)
    last_err = ""
    for cmd in _vision_compile_commands(staging):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            staging.unlink(missing_ok=True)
            if isinstance(exc, subprocess.CalledProcessError):
                last_err = (exc.stderr or b"").decode("utf-8", errors="replace")[-400:]
            else:
                last_err = str(exc)
            continue
        if not _helper_usable(staging):
            staging.unlink(missing_ok=True)
            last_err = "编出的识别程序架构不对（Apple 芯片须 arm64）"
            continue
        staging.replace(_BIN)
        break
    else:
        if last_err:
            print(f"编译本机识别失败：{last_err}", file=sys.stderr, flush=True)
        if _helper_usable(_BIN):
            return _BIN
        return None
    return _BIN if _helper_usable(_BIN) else None


def _cleanup_ocr_text(text: str) -> str:
    blob = text or ""
    blob = blob.replace("₺", "Ω").replace("ІРХХ", "IPXX").replace("ІР", "IP")
    blob = re.sub(r"[А-Яа-яЁё]{2,}", " ", blob)
    blob = re.sub(r"#{3,}", " ", blob)
    blob = re.sub(r"[ \t]{3,}", "  ", blob)
    return blob


def layout_ocr_text(raw: str) -> str:
    """Vision 输出 y\\tx\\ttext 时按行拼中英对照；旧版纯文本原样返回。"""
    rows: list[tuple[float, float, str]] = []
    fallback: list[str] = []
    for line in (raw or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            try:
                y_pos = float(parts[0])
                x_pos = float(parts[1])
            except ValueError:
                if line.strip():
                    fallback.append(line)
                continue
            text = parts[2].strip()
            if text:
                rows.append((y_pos, x_pos, text))
            continue
        if line.strip():
            fallback.append(line)
    if not rows:
        return _cleanup_ocr_text("\n".join(fallback))
    rows.sort(key=lambda item: (item[0], item[1]))
    grouped: list[tuple[float, list[tuple[float, str]]]] = []
    for y_pos, x_pos, text in rows:
        if grouped and abs(y_pos - grouped[-1][0]) <= 0.02:
            grouped[-1][1].append((x_pos, text))
        else:
            grouped.append((y_pos, [(x_pos, text)]))
    lines: list[str] = []
    for _y, items in grouped:
        items.sort(key=lambda item: item[0])
        lines.append("  ".join(text for _x, text in items))
    return _cleanup_ocr_text("\n".join(lines))


def _run_vision(helper: Path, image_path: Path) -> str:
    global _VISION_FAIL_LOGGED
    proc = subprocess.run(
        [str(helper), str(image_path)],
        timeout=90,
        capture_output=True,
    )
    if proc.returncode != 0:
        if not _VISION_FAIL_LOGGED:
            err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[-300:]
            print(f"本机 Vision 识别失败：{err or proc.returncode}", file=sys.stderr, flush=True)
            _VISION_FAIL_LOGGED = True
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def ocr_image(image_path: Path) -> str:
    scored: list[tuple[int, str]] = []
    rapid = _run_rapidocr(image_path)
    if rapid.strip():
        rapid_score = _ocr_text_score(rapid)
        scored.append((rapid_score, rapid))
        if rapid_score >= _RAPID_GOOD:
            return rapid
    if _page_ocr_ready():
        krow = _run_krow_ocr(image_path)
        if krow.strip():
            scored.append((_ocr_text_score(krow), krow))
            if scored and max(item[0] for item in scored) >= 80:
                return max(scored, key=lambda item: item[0])[1]
    if _page_ocr_ready() and scored:
        return max(scored, key=lambda item: item[0])[1]
    helper = _vision_bin()
    if helper is not None:
        for candidate in (image_path, _prepare_ocr_image(image_path)):
            try:
                text = layout_ocr_text(_run_vision(helper, candidate))
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
            if text.strip():
                scored.append((_ocr_text_score(text), text))
                break
    tess = _tesseract_bin()
    if tess and (not scored or max(item[0] for item in scored) < 90):
        prepared = _prepare_ocr_image(image_path)
        langs = _tesseract_langs(tess)
        try:
            first = _run_tesseract(tess, prepared, langs, "6")
            if _ocr_text_score(first) >= 90:
                scored.append((_ocr_text_score(first), _cleanup_ocr_text(first)))
            else:
                second = _run_tesseract(tess, prepared, langs, "4")
                best = second if _ocr_text_score(second) > _ocr_text_score(first) else first
                scored.append((_ocr_text_score(best), _cleanup_ocr_text(best)))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    best = max((item[0] for item in scored), default=0)
    if best < 80 and not _page_ocr_ready():
        site = _run_site_page_vision(image_path)
        if site.strip():
            scored.append((_ocr_text_score(site), site))
    if not scored:
        return ""
    return max(scored, key=lambda item: item[0])[1]


def sparse_pdf_pages(pdf_path: Path, page_count: int) -> list[int]:
    """页眉以外几乎没字、但又有大量矢量线的页（参数表经常是画出来的）。"""
    del page_count
    try:
        import fitz
    except ImportError:
        return []
    doc = fitz.open(str(pdf_path))
    try:
        candidates: list[tuple[int, int, int]] = []
        for i, page in enumerate(doc):
            if i < 2:
                continue
            text = (page.get_text() or "").strip()
            n_draw = len(page.get_drawings())
            n_img = len(page.get_images())
            native_kind = page_text_kind(text) if text else "other"
            if native_kind == "toc":
                continue
            if (len(text) < 1200 and n_draw >= 50) or (
                len(text) < 500 and n_img >= 5
            ):
                candidates.append((i + 1, n_draw + n_img * 20, len(text)))

        def rank(item: tuple[int, int, int]) -> tuple[int, int, int]:
            page, n_draw, tlen = item
            n_pages = max(doc.page_count, 1)
            zone = 0 if page / n_pages >= 0.22 else 1
            return (zone, -n_draw, tlen)

        candidates.sort(key=rank)
        return [page for page, _, _ in candidates[:MAX_OCR_PAGES]]
    finally:
        doc.close()


def scan_image_pages(pdf_path: Path, page_count: int) -> list[int]:
    """整页是图片、几乎没有可复制文字的扫描件。"""
    try:
        import fitz
    except ImportError:
        return list(range(1, min(page_count, MAX_SCAN_OCR_PAGES) + 1))
    doc = fitz.open(str(pdf_path))
    try:
        found: list[int] = []
        n_pages = min(page_count, doc.page_count)
        for i in range(n_pages):
            page = doc[i]
            text = (page.get_text() or "").strip()
            if len(text) >= 80 and page_text_kind(text) == "toc":
                continue
            n_img = len(page.get_images())
            if n_img or len(text) < 240:
                found.append(i + 1)
        if not found:
            found = list(range(1, n_pages + 1))
        if len(found) > MAX_SCAN_OCR_PAGES:
            start = 1 if found[0] == 1 and len(found) > 3 else 0
            found = found[start : start + MAX_SCAN_OCR_PAGES]
        return found
    finally:
        doc.close()


def ocr_pdf_pages(
    pdf_path: Path,
    pages: list[int],
    deadline: float | None = None,
    label: str = "表格图",
) -> dict[int, str]:
    if not pages or not ocr_available():
        return {}
    try:
        import fitz
    except ImportError:
        return {}
    doc = fitz.open(str(pdf_path))
    jobs: list[tuple[int, Path]] = []
    out: dict[int, str] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="electrical-ocr-") as tmp:
            tmp_path = Path(tmp)
            n = len(pages)
            for i, page_no in enumerate(pages, 1):
                if not checkpoint(stage="ocr"):
                    break
                if deadline is not None and time.perf_counter() >= deadline:
                    report(
                        "表格图识别已达时限，继续用已识别页抽取…",
                        percent=40,
                        stage="ocr",
                    )
                    break
                if page_no < 1 or page_no > doc.page_count:
                    continue
                report(
                    f"正在渲染{label}：第 {page_no} 页（{i}/{n}）",
                    percent=8 + int(8 * i / max(n, 1)),
                    stage="ocr",
                )
                page = doc[page_no - 1]
                zoom = _page_zoom(page)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                png = tmp_path / f"p{page_no}.png"
                pix.save(str(png))
                jobs.append((page_no, png))
            if not jobs:
                return {}
            workers = min(_ocr_workers(), len(jobs))
            done = 0
            total = len(jobs)

            def one(item: tuple[int, Path]) -> tuple[int, str]:
                page_no, image_path = item
                try:
                    return page_no, ocr_image(image_path)
                except (OSError, subprocess.SubprocessError, RuntimeError):
                    return page_no, ""

            def take(page_no: int, text: str) -> None:
                if _keep_ocr_page(text):
                    out[page_no] = text
                elif (text or "").strip() and page_no not in out:
                    out[page_no] = text

            report(
                f"本机识别{label}：{total} 页"
                + (f"，{workers} 路并行" if workers > 1 else ""),
                percent=16,
                stage="ocr",
            )
            if workers == 1:
                for page_no, image_path in jobs:
                    if not checkpoint(stage="ocr"):
                        break
                    if deadline is not None and time.perf_counter() >= deadline:
                        break
                    page_no, text = one((page_no, image_path))
                    done += 1
                    report(
                        f"本机识别{label}：第 {page_no} 页（{done}/{total}）",
                        percent=16 + int(24 * done / max(total, 1)),
                        stage="ocr",
                    )
                    take(page_no, text)
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(one, item) for item in jobs]
                    for fut in as_completed(futures):
                        page_no, text = fut.result()
                        done += 1
                        report(
                            f"本机识别{label}：已完成 {done}/{total} 页",
                            percent=16 + int(24 * done / max(total, 1)),
                            stage="ocr",
                        )
                        take(page_no, text)
    finally:
        doc.close()
    return out


def merge_ocr_into_markdown(markdown: str, ocr_by_page: dict[int, str]) -> str:
    if not ocr_by_page:
        return markdown
    updated = markdown
    for page_no, text in sorted(ocr_by_page.items()):
        block = f"\n\n[本页为本机 OCR]\n{text.strip()}\n"
        marker = f"## 第 {page_no} 页"
        if marker not in updated:
            updated += f"\n{marker}\n{block}"
            continue
        parts = updated.split(marker, 1)
        rest = parts[1]
        nxt = rest.find("\n## 第 ")
        if nxt == -1:
            parts[1] = rest + block
        else:
            parts[1] = rest[:nxt] + block + rest[nxt:]
        updated = parts[0] + marker + parts[1]
    return updated
