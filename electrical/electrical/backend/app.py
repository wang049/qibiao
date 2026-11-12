"""出表 HTTP 接口与页面。"""
from __future__ import annotations

import argparse
import webbrowser

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from electrical.backend.jobs import JobStore
from electrical.backend.llm import check_local_llm
from electrical.backend.paths import FRONTEND_DIR, HOST, OUTPUT_DIR, PORT

jobs = JobStore()
app = FastAPI(title="电子电器 · SOR填表", docs_url=None, redoc_url=None)


def _page_html() -> str:
    path = FRONTEND_DIR / "index.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8' />"
        "<title>电子电器 · SOR填表</title></head><body>"
        "<p>找不到界面文件。请确认 electrical/frontend/index.html 存在。</p>"
        "</body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        content=_page_html(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    ok, model, detail = check_local_llm()
    return {
        "ok": ok,
        "model": model,
        "endpoint": detail if ok else "",
        "detail": "" if ok else detail,
    }


@app.post("/api/jobs")
async def start_job(file: UploadFile = File(...)) -> dict[str, object]:
    data = await file.read()
    incoming, out = jobs.prepare_upload(file, data)
    try:
        job_id = jobs.start(file.filename, incoming, out)
    except HTTPException:
        incoming.unlink(missing_ok=True)
        raise
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, object]:
    return jobs.snapshot(job_id)


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict[str, object]:
    ctrl = jobs.control(job_id)
    ctrl.request_pause()
    jobs.update(job_id, status="pausing", message="将在本段结束后暂停…")
    return jobs.snapshot(job_id)


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict[str, object]:
    ctrl = jobs.control(job_id)
    ctrl.request_resume()
    jobs.update(job_id, status="running", message="已继续出表…")
    return jobs.snapshot(job_id)


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, object]:
    ctrl = jobs.control(job_id)
    ctrl.request_stop()
    jobs.update(
        job_id,
        status="stopping",
        message="将在本段结束后结束，并按已抽出内容出表…",
    )
    return jobs.snapshot(job_id)


@app.get("/files/{name}")
def download(name: str) -> FileResponse:
    path = (OUTPUT_DIR / name).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "找不到核对表")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电子电器 SOR 填表：工位本机出表")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    url = f"http://{HOST}:{args.port}/"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"工位本机出表（仅本机）：{url}", flush=True)
    print("规格书不出公网。本机模型服务需已启动。按 Ctrl+C 结束。", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning")
    return 0
