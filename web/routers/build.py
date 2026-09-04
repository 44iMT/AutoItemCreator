"""
构建页：页面 + 私有 API（upload / build / stream / qdrant status）

设计要点：
- build 走 subprocess 跑 core/builder.py：print 日志零改动直达页面，
  进程崩溃不影响服务；同一时刻只允许一个构建任务（rebuild 删库，双击两下会热闹）
- fields_map 走临时 json 文件传 CLI，不走 argv（中文+引号的编码坑）
- 必需列（商品编码/条码/名称）缺失、映射重名 → /build 拒绝；
  建议列（前后台类目）缺失 → 放行但警告（库结构有时真不需要类目列）
- 永远不信客户端：前端即时提示只是体验，后端再验一遍
"""
import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = ROOT / "web" / "uploads"

sys.path.insert(0, str(ROOT))  # 复用 builder 的映射表与清洗常量
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # web/（common 在这）
from core.builder import HQ_FIELDS_MAP
from web.common import _norm

# 必需：builder 清洗/嵌入的硬依赖；建议：撑下游 recategory 的范本质量
REQUIRED = ["商品编码", "商品条码", "商品名称"]
RECOMMENDED = ["前台类目名称", "后台类目名称"]

router = APIRouter(prefix="/api/build")  # 页面私有 API 统一前缀，避免与其他页面的 upload 等碰撞
pages = APIRouter()  # 页面路由不带前缀（前缀会把 GET / 变成 /api/build/）


# ═══════════════════════════════════════════════════
# 工具：表头归一匹配（_norm 在 web/common.py 共享）
# ═══════════════════════════════════════════════════
def match_headers(headers: list[str]) -> list[dict]:
    """原表头 → 自动匹配结果：suggested 非空=前端自动勾选并预填。"""
    # 归一后的默认映射键 → 标准名
    norm_map = {_norm(k): v for k, v in HQ_FIELDS_MAP.items()}
    out = []
    for h in headers:
        suggested = norm_map.get(_norm(h))
        out.append({"name": h, "suggested": suggested})
    return out


# ═══════════════════════════════════════════════════
# 路由：页面
# ═══════════════════════════════════════════════════
@pages.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent.parent / "pages" / "build.html").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════
# 路由：上传 → 表头识别
# ═══════════════════════════════════════════════════
@router.post("/upload")
async def upload(file: UploadFile):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "只收 xlsx/xls")

    file_id = uuid.uuid4().hex[:12]
    path = UPLOAD_DIR / f"{file_id}.xlsx"
    path.write_bytes(await file.read())

    import pandas as pd
    df = pd.read_excel(path, dtype=str, nrows=0)  # 只读表头
    headers = [str(c) for c in df.columns]

    return {
        "file_id": file_id,
        "filename": file.filename,
        "rows": len(pd.read_excel(path, dtype=str)),
        "headers": match_headers(headers),
        "required": REQUIRED,
        "recommended": RECOMMENDED,
        "standard_names": sorted(set(HQ_FIELDS_MAP.values())),
    }


# ═══════════════════════════════════════════════════
# 路由：构建（唯一任务闸 + 参数校验 + 子进程）
# ═══════════════════════════════════════════════════
class BuildReq(BaseModel):
    file_id: str
    fields_map: dict[str, str]


job = {"proc": None, "lines": [], "done": True}  # 单任务闸：同刻只允许一个构建


@router.post("/start")
def build(req: BuildReq):
    if not job["done"] and job["proc"] and job["proc"].poll() is None:
        raise HTTPException(409, "已有构建任务在跑，等它结束喵")

    excel = UPLOAD_DIR / f"{req.file_id}.xlsx"
    if not excel.exists():
        raise HTTPException(404, "上传文件已过期，重新上传")

    # 后端再验一遍：必需目标名齐不齐、映射名有没有重复/空
    targets = [v.strip() for v in req.fields_map.values() if v.strip()]
    missing = [c for c in REQUIRED if c not in targets]
    if missing:
        raise HTTPException(400, f"缺少必需字段映射: {missing}")
    if len(targets) != len(set(targets)):
        raise HTTPException(400, f"映射名重复: {[t for t in set(targets) if targets.count(t) > 1]}")
    src_missing = [k for k in req.fields_map if k not in _read_headers(excel)]
    if src_missing:
        raise HTTPException(400, f"映射里的源列在表里不存在: {src_missing}")

    warn = [c for c in RECOMMENDED if c not in targets]  # 放行但警告，随日志带下去

    fields_file = UPLOAD_DIR / f"{req.file_id}.json"
    fields_file.write_text(json.dumps(req.fields_map, ensure_ascii=False), encoding="utf-8")

    cmd = [sys.executable, "-X", "utf8", "-u", str(ROOT / "core" / "builder.py"),
           "--excel", str(excel), "--fields-json", str(fields_file)]

    job.update(proc=subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    ), lines=[f"[web] 字段映射: {req.fields_map}"]
        + ([f"[web] ⚠ 未映射建议字段 {warn}，范本库将缺类目信息"] if warn else []),
        done=False)

    def pump():
        for line in job["proc"].stdout:
            job["lines"].append(line.rstrip("\n"))
        job["proc"].wait()
        ok = job["proc"].returncode == 0
        job["lines"].append(f"[web] {'构建完成' if ok else '构建失败（退出码 ' + str(job['proc'].returncode) + '）'}")
        job["done"] = True

    threading.Thread(target=pump, daemon=True).start()
    return {"job_id": "current", "warnings": warn}


def _read_headers(excel: Path) -> list[str]:
    import pandas as pd
    return [str(c) for c in pd.read_excel(excel, dtype=str, nrows=0).columns]


# ═══════════════════════════════════════════════════
# 路由：库状态（存在性 + 点数）
# ═══════════════════════════════════════════════════
@router.get("/qdrant/status")
def qdrant_status():
    from config import qdrant_client, COLLECTION_NAME
    try:
        if qdrant_client.collection_exists(COLLECTION_NAME):
            return {"collection": COLLECTION_NAME, "exists": True,
                    "points": qdrant_client.count(COLLECTION_NAME, exact=True).count}
        return {"collection": COLLECTION_NAME, "exists": False, "points": 0}
    except Exception as e:  # Qdrant 没起：报给前端显示连接失败，不让页面等
        raise HTTPException(503, f"Qdrant 连不上: {e}")


# ═══════════════════════════════════════════════════
# 路由：任务状态（页面刷新后自动恢复日志流/按钮态用）
# ═══════════════════════════════════════════════════
@router.get("/status")
def job_status():
    return {"running": not (job["done"] or (job["proc"] and job["proc"].poll() is not None)),
            "lines": len(job["lines"])}


# ═══════════════════════════════════════════════════
# 路由：SSE 日志流
# ═══════════════════════════════════════════════════
@router.get("/stream")
def stream(after: int = 0):
    from fastapi.responses import StreamingResponse

    def gen():
        i = after
        idle = 0
        while True:
            while i < len(job["lines"]):
                yield f"data: {json.dumps({'i': i, 'line': job['lines'][i]}, ensure_ascii=False)}\n\n"
                i += 1
                idle = 0
            if job["done"] and i >= len(job["lines"]):
                yield f"data: {json.dumps({'i': i, 'done': True})}\n\n"
                return
            import time
            time.sleep(0.5)
            idle += 1
            if idle > 7200:  # 2h 无输出保护
                return

    return StreamingResponse(gen(), media_type="text/event-stream")
