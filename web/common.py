"""web 层共享工具（build / category 等页面公用的纯函数）"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "web" / "uploads"

# 类目文件目录：type → (目录, config 里的生效路径属性名)
CATEGORY_DIRS = {
    "third": ROOT / "data" / "third_category",
    "general": ROOT / "data" / "category",
}


def _norm(s: str) -> str:
    """表头宽度归一：strip + 全角转半角括号（商品价格(元) vs （元））。"""
    return s.strip().replace("（", "(").replace("）", ")")
