#!/bin/sh
# 在 macOS 上交叉打 Windows x64 绿色包（嵌入 Python + 预下载 wheels）。
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WIN="$ROOT/packaging/windows"
CACHE="$WIN/.cache"
DIST="$ROOT/dist"
STAGE="$DIST/electrical-krow-windows"
PY_VER="3.12.10"
PY_ZIP="python-${PY_VER}-embed-amd64.zip"
PY_URL="https://www.python.org/ftp/python/${PY_VER}/${PY_ZIP}"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
NAME="${PACK_NAME:-电子电器SOR填表-windows-x64}"
ELECTRICAL="${ELECTRICAL_ROOT:-$ROOT/electrical}"
if [ ! -d "$ELECTRICAL/electrical" ]; then
  ELECTRICAL="$ROOT/../electrical"
fi
MODULES="${MODULES_SRC:-$HOME/.venv/lib/python3.12/site-packages/modules}"
SDK_VER="$(sed -n 's/^krow-agent-sdk==//p' "$WIN/requirements.txt" | head -n 1)"
if [ -z "$SDK_VER" ]; then
  echo "读不到 krow-agent-sdk 版本：$WIN/requirements.txt" >&2
  exit 1
fi

if [ ! -d "$ELECTRICAL/electrical" ]; then
  echo "找不到 electrical：$ELECTRICAL" >&2
  exit 1
fi
if [ ! -d "$MODULES/document_reader" ]; then
  echo "找不到 modules.document_reader：$MODULES" >&2
  exit 1
fi

mkdir -p "$CACHE" "$DIST"
rm -rf "$STAGE"
mkdir -p "$STAGE/app/electrical" "$STAGE/app/modules" "$STAGE/wheels" "$STAGE/python"

if [ ! -f "$CACHE/$PY_ZIP" ]; then
  echo "下载嵌入式 Python $PY_VER …"
  curl -fsSL "$PY_URL" -o "$CACHE/$PY_ZIP"
fi
if [ ! -f "$CACHE/get-pip.py" ]; then
  echo "下载 get-pip.py …"
  curl -fsSL "$GET_PIP_URL" -o "$CACHE/get-pip.py"
fi

unzip -q -o "$CACHE/$PY_ZIP" -d "$STAGE/python"
cp "$CACHE/get-pip.py" "$STAGE/get-pip.py"

PTH="$(echo "$STAGE/python"/python*._pth)"
cp "$WIN/python312._pth" "$PTH"

echo "下载 Windows wheels …"
# pip 在 Mac 上不会自动带上 sys_platform==win32 的依赖，必须写进 requirements。
# pywebview 依赖 proxy_tools（仅 sdist），不能和 --only-binary=:all: 一起解析。
export PATH="${HOME}/.venv/bin:${HOME}/.local/bin:${PATH}"
CORE_REQ="$(mktemp)"
grep -v -E '^(pywebview|pythonnet|bottle|typing_extensions)' "$WIN/requirements.txt" > "$CORE_REQ"
pip download \
  --python-version 312 \
  --platform win_amd64 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all: \
  -d "$STAGE/wheels" \
  -r "$CORE_REQ" \
  pip setuptools wheel
rm -f "$CORE_REQ"
pip download \
  --python-version 312 \
  --platform win_amd64 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all: \
  --no-deps \
  -d "$STAGE/wheels" \
  pywebview pythonnet bottle typing_extensions
pip download \
  --python-version 312 \
  --platform win_amd64 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all: \
  -d "$STAGE/wheels" \
  pythonnet
# proxy_tools 只有 sdist。嵌入式 Python 没有完整构建环境，必须在打包装成
# py3-none-any.whl，现场 pip 才能 --only-binary 安装。
pip download -d "$STAGE/wheels" --no-deps proxy_tools
pip wheel --no-deps -w "$STAGE/wheels" "$STAGE/wheels"/proxy_tools-*.tar.gz
rm -f "$STAGE/wheels"/proxy_tools-*.tar.gz
if ls "$STAGE/wheels"/*.tar.gz >/dev/null 2>&1; then
  echo "wheels 里还有源码包，Windows 嵌入式 Python 装不上：" >&2
  ls -l "$STAGE/wheels"/*.tar.gz >&2
  exit 1
fi
if ! ls "$STAGE/wheels"/proxy_tools-*.whl >/dev/null 2>&1; then
  echo "没有打出 proxy_tools wheel" >&2
  exit 1
fi

echo "下载 Windows runtime ${SDK_VER}（与 SDK 同号，私有 index）…"
ROOT="$ROOT" STAGE="$STAGE" SDK_VER="$SDK_VER" python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

ver = os.environ["SDK_VER"].strip()
want = f"krow_agent_sdk_runtime-{ver}-cp312-cp312-win_amd64.whl"
stage = Path(os.environ["STAGE"]) / "wheels"
root = Path(os.environ["ROOT"])
key = (os.environ.get("PACK_RUNTIME_KEY") or os.environ.get("KROW_API_KEY") or "").strip()
if not key:
    cache = root / "output" / "krow-sdk-key.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    key = str(data.get("key") or "")
if not key.startswith("sk-"):
    raise SystemExit("no runtime API key; set KROW_API_KEY or PACK_RUNTIME_KEY")

from krow_sdk_install.client import RuntimeInstaller

with RuntimeInstaller(api_key=key, base_url="https://api.krow.cn") as installer:
    entries = installer.fetch_simple_index()
    entry = next((e for e in entries if e.filename == want), None)
    if entry is None:
        names = ", ".join(sorted(e.filename for e in entries))
        raise SystemExit(f"runtime index missing {want}: {names}")
    path = installer.download_wheel(entry, output_dir=stage)
print("pack runtime", path.name, path.stat().st_size, file=sys.stderr)
PY

echo "复制程序 …"
rsync -a \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$ROOT/electrical_krow/" "$STAGE/app/electrical_krow/"
rsync -a \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'frontend' \
  --exclude 'backend' \
  --exclude 'demo.py' \
  --exclude 'eval.py' \
  "$ELECTRICAL/electrical/" "$STAGE/app/electrical/electrical/"
if ls "$STAGE/wheels"/krow_agent_sdk_runtime-*.whl >/dev/null 2>&1; then
  echo "runtime wheel 已入包，不再把 Mac 的 modules 拷进 app（避免挡住 Windows runtime）"
else
  rsync -a \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '*.so' \
    "$MODULES/document_reader/" "$STAGE/app/modules/document_reader/"
  cp "$MODULES/__init__.py" "$STAGE/app/modules/__init__.py"
fi
mkdir -p "$STAGE/app/docs"
cp "$ROOT/docs/clause_lexicon.json" "$STAGE/app/docs/clause_lexicon.json"
mkdir -p "$STAGE/app/docs/knowledge/published"
cp "$ROOT/docs/knowledge/published/manifest.json" "$STAGE/app/docs/knowledge/published/manifest.json"
cp "$ROOT/docs/knowledge/published/graph.json" "$STAGE/app/docs/knowledge/published/graph.json"
cp "$ROOT/docs/knowledge/published/keyword_index.json" "$STAGE/app/docs/knowledge/published/keyword_index.json"
for extra in arch_kb.yaml hsi_kb.yaml; do
  if [ -f "$ROOT/docs/knowledge/$extra" ]; then
    cp "$ROOT/docs/knowledge/$extra" "$STAGE/app/docs/knowledge/$extra"
  fi
done
# 待专家口径标注（出表时写进复核备注）；文件可为空/不存在
if [ -f "$ROOT/docs/knowledge/pending_rulings.json" ]; then
  cp "$ROOT/docs/knowledge/pending_rulings.json" "$STAGE/app/docs/knowledge/pending_rulings.json"
fi

cp "$WIN/config.ini" "$STAGE/config.ini"
if [ -n "${PACK_SERVER_URL:-}" ]; then
  PACK_SERVER_URL="$PACK_SERVER_URL" STAGE="$STAGE" python3 - <<'PY'
import os
import re
from pathlib import Path

url = os.environ["PACK_SERVER_URL"].strip().rstrip("/")
ini = Path(os.environ["STAGE"]) / "config.ini"
text = ini.read_text(encoding="utf-8")
text, n = re.subn(r"(?m)^server_url\s*=\s*.*$", f"server_url = {url}", text, count=1)
if n != 1:
    raise SystemExit("failed to set server_url in staged config.ini")
text = text.replace(
    "本包默认连公网联调 https://api.krow.cn。",
    f"本包默认连 {url}。",
)
if url.rstrip("/") == "https://rdapi.aurobaytech-t.com":
    if re.search(r"(?m)^lock_environment\s*=", text):
        text, _ = re.subn(
            r"(?m)^lock_environment\s*=\s*.*$",
            "lock_environment = true",
            text,
            count=1,
        )
    else:
        text = text.rstrip() + "\nlock_environment = true\n"
ini.write_text(text, encoding="utf-8")
print("pack server_url", url)
PY
fi
cp "$WIN/requirements.txt" "$STAGE/requirements.txt"
cp "$WIN/run.py" "$STAGE/run.py"
cp "$WIN/sitecustomize.py" "$STAGE/sitecustomize.py"
python3 - <<PY
from pathlib import Path
win = Path(r'''$WIN''')
stage = Path(r'''$STAGE''')

def crlf_ascii(src: Path, dest: Path) -> None:
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    dest.write_bytes(text.encode("ascii", errors="strict"))

def crlf_gbk(src: Path, dest: Path) -> None:
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    dest.write_bytes(text.encode("gbk"))

def crlf_utf16(src: Path, dest: Path) -> None:
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    dest.write_bytes(text.encode("utf-16"))

crlf_gbk(win / "start.bat", stage / "start.bat")
crlf_gbk(win / "console.bat", stage / "console.bat")
crlf_ascii(win / "python312._pth", stage / "python312._pth")
crlf_ascii(win / "python312._pth", stage / "python" / "python312._pth")
crlf_utf16(win / "start.vbs", stage / "start.vbs")
crlf_utf16(win / "start.vbs", stage / "启动SOR填表.vbs")
crlf_utf16(win / "stop.vbs", stage / "stop.vbs")
crlf_utf16(win / "stop.vbs", stage / "停止SOR填表.vbs")
readme = (win / "使用说明.txt").read_text(encoding="utf-8")
(stage / "README.txt").write_bytes(b"\xef\xbb\xbf" + readme.encode("utf-8"))
onsite = (win / "现场开通请提供.txt").read_text(encoding="utf-8")
(stage / "现场开通请提供.txt").write_bytes(b"\xef\xbb\xbf" + onsite.encode("utf-8"))
print("wrote CRLF start.bat / vbs")
PY

if [ -n "${PACK_SERVER_URL:-}" ]; then
  PACK_SERVER_URL="$PACK_SERVER_URL" STAGE="$STAGE" python3 - <<'PY'
import os
from pathlib import Path

url = os.environ["PACK_SERVER_URL"].strip().rstrip("/")
readme = Path(os.environ["STAGE"]) / "README.txt"
raw = readme.read_bytes()
bom = raw.startswith(b"\xef\xbb\xbf")
text = (raw[3:] if bom else raw).decode("utf-8")
old = "本包默认 https://api.krow.cn。"
new = f"本包默认 {url}。"
if old not in text:
    raise SystemExit("README.txt missing default server_url sentence")
readme.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.replace(old, new, 1).encode("utf-8"))
print("pack README server_url", url)
PY
fi

echo "预装依赖到嵌入式 Python（现场不再 pip）…"
STAGE="$STAGE" WIN="$WIN" python3 - <<'PY'
import os
import zipfile
from pathlib import Path

stage = Path(os.environ["STAGE"])
win = Path(os.environ["WIN"])
site = stage / "python" / "Lib" / "site-packages"
site.mkdir(parents=True, exist_ok=True)
site_resolved = site.resolve()

SKIP_TOP = {"examples", "pip", "wheel", "pythonwin"}
SKIP_DIST_PREFIXES = ("pip-", "wheel-")

def skip_mapped(mapped: str) -> bool:
    parts = [p for p in mapped.replace("\\", "/").split("/") if p]
    if not parts:
        return True
    top = parts[0]
    if top in SKIP_TOP:
        return True
    if top.endswith(".dist-info") and top.startswith(SKIP_DIST_PREFIXES):
        return True
    if "examples" in parts or mapped.endswith(".pyc") or "__pycache__" in parts:
        return True
    return False

def unpack_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        for item in zf.infolist():
            path = item.filename.replace("\\", "/")
            if not path or path.endswith("/"):
                continue
            parts = path.split("/")
            mapped = path
            data_at = next((i for i, p in enumerate(parts) if p.endswith(".data")), None)
            if data_at is not None:
                kind = parts[data_at + 1] if data_at + 1 < len(parts) else ""
                rest = "/".join(parts[data_at + 2 :])
                if kind not in {"purelib", "platlib"} or not rest:
                    continue
                mapped = rest
            if skip_mapped(mapped):
                continue
            target = site.joinpath(*mapped.split("/"))
            try:
                target.resolve().relative_to(site_resolved)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(item))

wheels = sorted((stage / "wheels").glob("*.whl"))
if not wheels:
    raise SystemExit("no wheels to preinstall")
for wheel in wheels:
    unpack_wheel(wheel)

needed = {
    "httpx": site / "httpx",
    "httpcore": site / "httpcore",
    "anyio": site / "anyio",
    "certifi": site / "certifi",
    "webview": site / "webview",
    "krow_agent_sdk": site / "krow_agent_sdk",
    "fastapi": site / "fastapi",
    "pythonnet": site / "pythonnet",
    "clr_loader": site / "clr_loader",
    "modules": site / "modules",
}
missing = [name for name, path in needed.items() if not path.exists()]
if not list(site.glob("krow_agent_sdk_runtime-*.dist-info")):
    missing.append("krow_agent_sdk_runtime")
if missing:
    raise SystemExit("preinstall missing: " + ", ".join(missing))
(site / "sitecustomize.py").write_bytes((win / "sitecustomize.py").read_bytes())
(stage / "python" / ".deps-ok").write_text("ok\n", encoding="ascii")
print("preinstall", len(wheels), "wheels ->", site)
PY
rm -rf "$STAGE/wheels"
rm -f "$STAGE/get-pip.py"
# requirements 仅作记录；现场不再 pip
rm -f "$STAGE/requirements.txt"

echo "交叉编译 Windows 启动程序 …"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) ZIG_ARCH=aarch64 ;;
  x86_64) ZIG_ARCH=x86_64 ;;
  *) echo "不支持的本机架构：$ARCH" >&2; exit 1 ;;
esac
ZIG_VER="0.13.0"
ZIG_NAME="zig-macos-${ZIG_ARCH}-${ZIG_VER}"
ZIG_TAR="${ZIG_NAME}.tar.xz"
ZIG_BIN="$CACHE/$ZIG_NAME/zig"
if [ ! -x "$ZIG_BIN" ]; then
  if [ ! -f "$CACHE/$ZIG_TAR" ]; then
    echo "下载 Zig $ZIG_VER …"
    curl -fL --retry 8 --retry-all-errors --retry-delay 3 -C - \
      "https://ziglang.org/download/${ZIG_VER}/${ZIG_TAR}" \
      -o "$CACHE/$ZIG_TAR"
  fi
  tar -xJf "$CACHE/$ZIG_TAR" -C "$CACHE"
fi
"$ZIG_BIN" build-exe "$WIN/app.c" \
  -target x86_64-windows-gnu \
  -O ReleaseSmall \
  --subsystem windows \
  -lc -lshell32 -luser32 -lkernel32 -lgdi32 -liphlpapi -lws2_32 -lole32 -luuid \
  -femit-bin="$STAGE/SORFill.exe"
"$ZIG_BIN" build-exe "$WIN/app.c" \
  -target x86_64-windows-gnu \
  -O ReleaseSmall \
  --subsystem windows \
  -cflags -DSTOP_APP -- \
  -lc -lshell32 -luser32 -lkernel32 -lgdi32 -liphlpapi -lws2_32 -lole32 -luuid \
  -femit-bin="$STAGE/SORStop.exe"
cp "$ROOT/electrical_krow/frontend/app-icon.ico" "$STAGE/app-icon.ico"
python3 "$WIN/embed_icon.py" "$STAGE/SORFill.exe" "$STAGE/app-icon.ico"
python3 "$WIN/embed_icon.py" "$STAGE/SORStop.exe" "$STAGE/app-icon.ico"
cp "$STAGE/SORFill.exe" "$STAGE/启动SOR填表.exe"
cp "$STAGE/SORStop.exe" "$STAGE/停止SOR填表.exe"

ZIP="$DIST/${NAME}.zip"
EXE="$DIST/${NAME}.exe"
rm -f "$ZIP" "$EXE"
python3 - <<PY
import io
import os
import struct
import zipfile
from pathlib import Path

stage = Path(r'''$STAGE''')
zip_path = Path(r'''$ZIP''')
exe_path = Path(r'''$EXE''')
stub = (stage / "SORFill.exe").read_bytes()
base = "electrical-krow-windows"
magic = b"EKROWZP1"

def add_tree(zf, root, prefix=None):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        name = f"{prefix}/{rel}" if prefix else rel
        info = zipfile.ZipInfo(name)
        info.flag_bits |= 0x800
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, p.read_bytes())

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    add_tree(zf, stage, base)
print("zip", zip_path)

payload = io.BytesIO()
with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
    add_tree(zf, stage, None)
blob = payload.getvalue()
if blob[:2] != b"PK":
    raise SystemExit("payload is not a zip")
with exe_path.open("wb") as f:
    f.write(stub)
    f.write(magic)
    f.write(struct.pack("<Q", len(blob)))
    f.write(blob)

with zipfile.ZipFile(io.BytesIO(blob), "r") as zf:
    names = zf.namelist()
    if "run.py" not in names:
        raise SystemExit("exe overlay zip missing run.py: " + ", ".join(names[:12]))
    if "app/docs/clause_lexicon.json" not in names:
        raise SystemExit("exe overlay zip missing clause_lexicon.json")
    if "app/docs/knowledge/published/manifest.json" not in names:
        raise SystemExit("exe overlay zip missing knowledge manifest")
    if "app/docs/knowledge/published/graph.json" not in names:
        raise SystemExit("exe overlay zip missing knowledge graph")
    if "SORFill.exe" not in names:
        raise SystemExit("exe overlay zip missing SORFill.exe")
    if "app-icon.ico" not in names:
        raise SystemExit("exe overlay zip missing app-icon.ico")
    if b".rsrc" not in stub:
        raise SystemExit("SORFill.exe missing icon resource")
    if "python/.deps-ok" not in names:
        raise SystemExit("exe overlay zip missing preinstalled python/.deps-ok")
    if not any(n.startswith("python/Lib/site-packages/webview/") for n in names):
        raise SystemExit("exe overlay zip missing preinstalled webview")
    if not any("proxy_tools" in n and n.startswith("python/Lib/site-packages/") for n in names):
        raise SystemExit("missing preinstalled proxy_tools")
    if any(n.endswith(".tar.gz") for n in names):
        raise SystemExit("pack still contains sdists")
    if any(n.startswith("wheels/") for n in names):
        raise SystemExit("wheels/ should not ship after preinstall")
    if "python/Lib/site-packages/httpx/__init__.py" not in names:
        raise SystemExit("exe overlay zip missing preinstalled httpx")
    if not any(n.startswith("python/Lib/site-packages/httpcore/") for n in names):
        raise SystemExit("exe overlay zip missing preinstalled httpcore")
    if any(n.startswith("python/Lib/site-packages/examples/") for n in names):
        raise SystemExit("examples/ should not ship")
    if not any(n.startswith("python/Lib/site-packages/modules/") for n in names):
        raise SystemExit("exe overlay zip missing runtime modules")
    if not any(n.startswith("python/Lib/site-packages/krow_agent_sdk_runtime-") and n.endswith(".dist-info/METADATA") for n in names):
        raise SystemExit("exe overlay zip missing krow-agent-sdk-runtime")
    want = (os.environ.get("PACK_SERVER_URL") or "").strip().rstrip("/")
    if want:
        ini = zf.read("config.ini").decode("utf-8")
        if f"server_url = {want}" not in ini:
            raise SystemExit("staged config.ini missing PACK_SERVER_URL")
        if want == "https://rdapi.aurobaytech-t.com" and "lock_environment = true" not in ini:
            raise SystemExit("site pack missing lock_environment")
raw = exe_path.read_bytes()
idx = len(stub)
if raw[idx : idx + 8] != magic or raw[idx + 8 : idx + 16] != struct.pack("<Q", len(blob)):
    raise SystemExit("exe missing zip payload magic after stub")
if raw[idx + 16 : idx + 18] != b"PK":
    raise SystemExit("exe payload is not a zip")
print("exe", exe_path, "files", len(names), "payload", len(blob))
print("preinstalled, no field pip")
PY

echo "已生成："
ls -lh "$ZIP" "$EXE"
