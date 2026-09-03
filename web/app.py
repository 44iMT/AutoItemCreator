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

# 启动清场：上次会话留下的临时上传/映射文件全删（服务重启=页面状态已失，留着也没人认领）
for _f in UPLOAD_DIR.iterdir():
    _f.unlink() if _f.is_file() else None

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # web/ 自身（routers 包在这）

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    # 裁紧版（viewBox 6 6 52 52）：标签页 16px 下六边形占满，原版留白在小尺寸会被吃掉
    return FileResponse(ROOT / "web" / "static" / "aic-favicon.svg", media_type="image/svg+xml")


from routers import build  # noqa: E402（需在 sys.path 就位后导入）
app.include_router(build.pages)   # 页面路由（GET / 等，无前缀）
app.include_router(build.router)  # 私有 API（/api/build/*）
