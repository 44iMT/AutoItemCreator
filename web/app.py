"""
AIC Web 组装层：只负责 create_app / static / favicon / uploads 生命周期 / 注册路由。

页面即领域：每个页面一个 routers/*.py（页面路由 + 私有 API + 自身任务状态），
加新页面 = 新增 router 文件 + 这里一行 include_router。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "web" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 启动清场：上次会话留下的临时上传/映射文件全删（服务重启=页面状态已失，留着也没人认领）。
# .gitkeep 除外——它是 git 占位（.gitignore 里为它开了例外），删了 clone 下来就没这目录了
for _f in UPLOAD_DIR.iterdir():
    if _f.is_file() and _f.name != ".gitkeep":
        _f.unlink()

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # web/ 自身（routers 包在这）

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.common import render

app = FastAPI()
app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    # 裁紧版（viewBox 6 6 52 52）：标签页 16px 下六边形占满，原版留白在小尺寸会被吃掉
    return FileResponse(ROOT / "web" / "static" / "aic-favicon.svg", media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def home():
    """首页：静态指路牌（三步流程卡），无 JS 无 API。"""
    return render("home.html", "home")


# 桌面壳心跳：页面每 5s ping，desktop.py 侧超时判离线收摊（窗口与服务分进程的黏合剂）
import time as _time
last_heartbeat = [_time.time()]


@app.get("/api/heartbeat")
def heartbeat():
    last_heartbeat[0] = _time.time()
    return {"ok": True}


from web.routers import build, category, run  # noqa: E402（统一从 web. 走，防双路径导入出两份 job）
app.include_router(build.pages)      # 页面路由（GET / 等，无前缀）
app.include_router(build.router)     # 私有 API（/api/build/*）
app.include_router(category.pages)   # 类目页（GET /category）
app.include_router(category.router)  # 类目 API（/api/category/*）
app.include_router(run.pages)        # 执行页（GET /run）
app.include_router(run.router)       # 执行 API（/api/run/*）
