"""
执行页：上传商品表 → 全参数配置 → 子进程跑 core/run_task.py → SSE 日志 → 停止

v2 通用化：start 不再组装 recategory 特例，页面给什么透传什么（校验后）。
预设（data/presets/*.json）= 完整任务配置的命名快照，选了自动填满表单。
护栏不变：单任务闸、模板占位符与注入联动校验、缓存键必须来自已映射列。
后续：QA agent 帮填参数——表单 config 对象 + 字段 description 就是它的地基。
"""
import json
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = ROOT / "web" / "uploads"
RUNS_DIR = ROOT / "data" / "runs"      # 每次执行的配置快照（审计留档）
PRESET_DIR = ROOT / "data" / "presets"

# 教学型默认模板（去任务指向）：新任务的起点，任务配置活在预设里。
# 硬编码——没有保存按钮、纯只读常量，住代码里 clone 即用（data/ 不进 git）
DEFAULT_CONFIG = {
    "system_prompt": "你是数据处理专家。请根据输入字段完成 {任务目标}，必要时使用工具查询。\n\n"
                     "参考数据已直接附在下方：\n\n{{参考数据}}\n\n"
                     "所有返回字段均采用字符串类型。\n\n只输出 JSON，不要 markdown 包裹。",
    "out_columns": {"输出列名": "告诉模型这个字段填什么、什么格式（示例行，改掉我）"},
    "tools": [],
    "category": {},
    "injections": {},
    "concurrency": 4, "retry_times": 3, "include_input": True, "log_tag": "Task",
    "reuse": {"collection": "", "exact_fields": [], "vector_fields": [], "vector_threshold": 0.95},
}

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.common import _norm, CATEGORY_DIRS, render, worker_cmd

# 工具注册表（与 core/run_task.py 同源；agent 工具面 = 页面多选框选项）
sys.path.insert(0, str(ROOT))
TOOL_REGISTRY = {
    "search_products": "向量搜索总部商品库（名称→范本）",
    "search_by_barcode": "条码精确查总部商品",
    "web_search": "联网搜索兜底",
    "get_categories": "读通用类目表",
    "get_third_categories": "读三方类目表",
}

router = APIRouter(prefix="/api/run")
pages = APIRouter()


# ═══════════════════════════════════════════════════
# 页面
# ═══════════════════════════════════════════════════
@pages.get("/run", response_class=HTMLResponse)
def index():
    return render("run.html", "run")


# ═══════════════════════════════════════════════════
# 上传 / 清单类 API
# ═══════════════════════════════════════════════════
@router.post("/upload")
async def upload(file: UploadFile):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "只收 xlsx/xls")
    file_id = uuid.uuid4().hex[:12]
    path = UPLOAD_DIR / f"{file_id}.xlsx"
    path.write_bytes(await file.read())

    import pandas as pd
    from starlette.concurrency import run_in_threadpool
    df = await run_in_threadpool(pd.read_excel, path, dtype=str, nrows=0)
    headers = [_norm(str(c)) for c in df.columns]
    return {"file_id": file_id, "filename": file.filename,
            "rows": len(await run_in_threadpool(pd.read_excel, path, dtype=str)),
            "headers": headers,
            "desktop": _desktop(),
            "tools": [{"name": k, "desc": v} for k, v in TOOL_REGISTRY.items()]}


def _desktop() -> str:
    """Windows 真实桌面路径：注册表 Known Folder 优先（防 OneDrive 重定向），退 expanduser。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "Desktop")
        import os
        return os.path.expandvars(val)
    except Exception:
        import os
        return os.path.join(os.path.expanduser("~"), "Desktop")


@router.get("/categories")
def list_categories():
    out = {}
    for key in ("third", "general"):
        d = CATEGORY_DIRS[key]
        files = []
        if d.exists():
            for f in sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
                rows = max(0, len(f.read_text(encoding="utf-8-sig").splitlines()) - 1)
                files.append({"name": f.name, "rows": rows})
        out[key] = files
    return out


@router.get("/defaults")
def get_defaults():
    """教学型默认模板（去任务指向）：新任务的起点，任务配置活在预设里。"""
    return DEFAULT_CONFIG


# ═══════════════════════════════════════════════════
# 预设：完整任务配置的命名快照
# ═══════════════════════════════════════════════════
@router.get("/presets")
def list_presets():
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(PRESET_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": f.stem, "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M"),
                        "task": data.get("task", "")})
        except Exception:
            pass
    return {"presets": out}


@router.get("/preset/{name}")
def get_preset(name: str):
    p = PRESET_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"预设不存在: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


@router.post("/preset")
def save_preset(req: dict):
    name = (req.get("name") or "").strip()
    if not name or not all(c.isalnum() or c in "_-一-鿿" for c in name):
        raise HTTPException(400, "预设名只允许中文/字母/数字/_-")
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    (PRESET_DIR / f"{name}.json").write_text(
        json.dumps(req.get("config"), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": name}


@router.delete("/preset/{name}")
def delete_preset(name: str):
    p = PRESET_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, "预设不存在")
    p.unlink()
    return {"deleted": name}


# ═══════════════════════════════════════════════════
# 启动（全参数透传 + 推导校验）
# ═══════════════════════════════════════════════════
class StartReq(BaseModel):
    file_id: str
    output_path: str = ""                # 结果 xlsx 完整路径；空 = 上传目录自动命名
    columns_map: dict[str, str]          # {展示名: 源列名}
    out_columns: dict[str, str]           # {输出列名: 字段说明}
    system_prompt: str
    tools: list[str]
    category: dict[str, str]              # {"third": ..., "general": ...} 可空
    injections: dict[str, dict]           # {"{{x}}": {"tool":..., "intro":..., "enabled":...}}
    concurrency: int = 4
    retry_times: int = 3
    include_input: bool = True
    log_tag: str = "Task"
    reuse: Optional[dict] = None          # {collection, exact_fields, vector_fields, vector_threshold}；null=禁用缓存


job = {"proc": None, "lines": [], "done": True, "task_file": None}


@router.post("/start")
def start(req: StartReq):
    if not job["done"] and job["proc"] and job["proc"].poll() is None:
        raise HTTPException(409, "已有执行任务在跑，先停它或等它结束喵")

    excel = UPLOAD_DIR / f"{req.file_id}.xlsx"
    if not excel.exists():
        raise HTTPException(404, "上传文件已过期，重新上传")

    mapped = {k: v for k, v in req.columns_map.items() if k.strip() and v.strip()}
    if not mapped:
        raise HTTPException(400, "列映射为空：至少勾选一列")
    if len(set(mapped.values())) != len(mapped):
        dup = [v for v in set(mapped.values()) if list(mapped.values()).count(v) > 1]
        raise HTTPException(400, f"多个展示名映射到同一源列: {dup}")
    if not req.out_columns:
        raise HTTPException(400, "输出列为空：至少定义一个")
    unknown = [t for t in req.tools if t not in TOOL_REGISTRY]
    if unknown:
        raise HTTPException(400, f"未注册的工具: {unknown}")

    # 类目表：路径必须在对应类型目录内（白名单校验），不存在即报
    category = {}
    for key in ("third", "general"):
        fname = (req.category or {}).get(key)
        if fname:
            p = CATEGORY_DIRS[key] / fname
            if not p.exists():
                raise HTTPException(400, f"类目表不存在: {fname}")
            category[key] = str(p)

    # 注入：显式禁用的才剔除（缺省视为启用——裸 API 调用不带 enabled 时不静默丢注入）
    injections = {}
    for slot, inj in (req.injections or {}).items():
        if inj.get("enabled", True) is False:
            continue
        if inj.get("tool") not in TOOL_REGISTRY:
            raise HTTPException(400, f"注入 {slot} 的工具未注册: {inj.get('tool')}")
        if slot not in req.system_prompt:
            raise HTTPException(400, f"注入 {slot} 的占位符不在模板里")
        injections[slot] = {"tool": inj["tool"]}  # 引导文字属模板文案，写在模板里

    reuse = req.reuse or {}
    if reuse.get("vector_fields") and reuse.get("vector_threshold") is None:
        raise HTTPException(400, "开了向量缓存就必须给阈值")
    bad_exact = [c for c in reuse.get("exact_fields", []) if c not in mapped]
    bad_vec = [c for c in reuse.get("vector_fields", []) if c not in mapped]
    if bad_exact or bad_vec:
        raise HTTPException(400, f"缓存键列未在列映射中: {bad_exact + bad_vec}")

    # 输出路径：给了就用（目录自动创建），没给走上传目录自动命名
    if req.output_path:
        out = Path(req.output_path)
        if not str(out).endswith(".xlsx"):
            raise HTTPException(400, "输出路径要以 .xlsx 结尾")
        out.parent.mkdir(parents=True, exist_ok=True)
        output_file = str(out)
    else:
        output_file = str(UPLOAD_DIR / f"{req.file_id}-结果.xlsx")

    task = {
        "input_file": str(excel),
        "output_file": output_file,
        "columns_map": mapped,
        "out_columns": req.out_columns,
        "system_prompt": req.system_prompt,
        "tools": req.tools,
        "category": category,
        "injections": injections,
        "concurrency": req.concurrency,
        "retry_times": req.retry_times,
        "include_input": req.include_input,
        "log_tag": req.log_tag or "Task",
        "reuse": reuse or None,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    task_file = RUNS_DIR / f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{req.file_id}.json"
    task_file.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = worker_cmd("run_task.py", ["--config", str(task_file)])

    job.update(proc=subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    ), lines=[f"[web] 任务快照: {task_file.name}"]
        + ([f"[web] 类目表: {category}"] if category else []),
        done=False, task_file=str(task_file), reuse_on=bool(task["reuse"]))

    def pump():
        for line in job["proc"].stdout:
            job["lines"].append(line.rstrip("\n"))
        job["proc"].wait()
        rc = job["proc"].returncode
        if rc == 0:
            job["lines"].append(f"[web] 执行完成 → {task['output_file']}")
        else:
            job["lines"].append(f"[web] 执行失败/停止（退出码 {rc}）——{_resume_hint()}")
        job["done"] = True

    threading.Thread(target=pump, daemon=True).start()
    return {"job_id": "current", "task_file": str(task_file)}


# ═══════════════════════════════════════════════════
# 状态 / 停止 / SSE / 结果
# ═══════════════════════════════════════════════════
@router.get("/status")
def job_status():
    return {"running": not (job["done"] or (job["proc"] and job["proc"].poll() is not None)),
            "lines": len(job["lines"]), "output": _output_path()}


def _resume_hint() -> str:
    """停止/中断后的续跑提示，按本次任务是否真启用了缓存说话，不误导。"""
    return "已完成的行在缓存中，重跑即续" if job.get("reuse_on") else "本次未启用缓存，重跑将从头执行"


@router.post("/stop")
def stop():
    if job["done"] or not job["proc"] or job["proc"].poll() is not None:
        raise HTTPException(400, "没有在跑的任务")
    job["proc"].terminate()
    job["lines"].append(f"[web] 收到停止请求，终止子进程…（{_resume_hint()}）")
    return {"stopping": True}


@router.get("/result")
def result():
    p = _output_path()
    if not p or not Path(p).exists():
        raise HTTPException(404, "结果文件还没生成")
    return FileResponse(p, filename=Path(p).name)


def _output_path():
    if not job.get("task_file"):
        return None
    return json.loads(Path(job["task_file"]).read_text(encoding="utf-8"))["output_file"]


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
            if idle > 7200:
                return

    return StreamingResponse(gen(), media_type="text/event-stream")
