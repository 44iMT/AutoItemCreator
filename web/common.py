"""web 层共享工具（build / category / run / home 公用的纯函数与渲染器）"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "web" / "uploads"

# Jinja2 渲染器：base.html（token CSS + 侧边栏）唯一定义，active 控制导航高亮
_env = Environment(loader=FileSystemLoader(ROOT / "web" / "pages"),
                   autoescape=select_autoescape(["html"]))


def render(page: str, active: str, **kw) -> str:
    return _env.get_template(page).render(active=active, **kw)


# ── 子进程 worker 命令 ──
# dev：python 直跑脚本；frozen（PyInstaller）：exe 自调用 worker 模式
# （打包后磁盘上没有 .py，exe 也不是解释器——唯一姿势是 exe 重入自己）
# flag 协议单点定义：--worker-{tag}，desktop.py 的 _maybe_worker 按 tag 分发
import sys as _sys

FROZEN = bool(getattr(_sys, "frozen", False))
_WORKER_TAGS = {"builder.py": "build", "run_task.py": "task"}


def worker_cmd(script: str, args: list) -> list:
    """script: 'builder.py' / 'run_task.py'；args 为脚本参数。"""
    if FROZEN:
        return [_sys.executable, f"--worker-{_WORKER_TAGS[script]}", *args]
    return [_sys.executable, "-X", "utf8", "-u", str(ROOT / "core" / script), *args]

# 类目文件目录：type → (目录, config 里的生效路径属性名)
CATEGORY_DIRS = {
    "third": ROOT / "data" / "third_category",
    "general": ROOT / "data" / "category",
}


def _norm(s: str) -> str:
    """表头宽度归一：strip + 全角转半角括号（商品价格(元) vs （元））。"""
    return s.strip().replace("（", "(").replace("）", ")")
