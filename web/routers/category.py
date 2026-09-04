"""
类目页：商家类目 xlsx → 单列 csv 白名单（平台无关）

模型：N 列有序选择（点击顺序 = 层级顺序），跳空可选（默认跳：空级别不拼接；
严格模式：任一级为空整行丢弃）。类型由目标目录区分：third/general。
护栏：生效文件（config 指向的）禁删禁覆盖无关提示——删除直接 400。
"""
import re
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.common import _norm, CATEGORY_DIRS

# 文件名白名单：中文/字母/数字/下划线/连字符，禁路径分隔（防 ../ 逃逸）
_SAFE_NAME = re.compile(r"^[\w一-鿿-]+\.csv$")

router = APIRouter(prefix="/api/category")
pages = APIRouter()


def _active_file(category_type: str) -> Path:
    """config 里当前生效的文件路径（third → THIRD_CATEGORY_FILE，general → CATEGORY_FILE）。"""
    from config import CATEGORY_FILE, THIRD_CATEGORY_FILE
    return Path(THIRD_CATEGORY_FILE if category_type == "third" else CATEGORY_FILE)


def _dir_of(category_type: str) -> Path:
    d = CATEGORY_DIRS.get(category_type)
    if d is None:
        raise HTTPException(400, f"未知类型: {category_type}（third/general）")
    return d


# ═══════════════════════════════════════════════════
# 转换核心（纯函数，预览/落盘共用）
# ═══════════════════════════════════════════════════
def convert(rows: list[dict], cols: list[str], sep: str, skip_empty: bool) -> dict:
    """
    rows=原始行dict列表，cols=按层级顺序选的列名。
    skip_empty=True  → 空级别跳过，全空的行丢弃
    skip_empty=False → 任一级为空整行丢弃（严格模式）
    返回 {lines, 跳过空行, 空级别跳过, 重复去重}
    """
    seen, lines, empty_rows, skipped_parts = set(), [], 0, 0
    for row in rows:
        vals = [str(row.get(c) or "").strip() for c in cols]
        if skip_empty:
            parts = [v for v in vals if v]
            skipped_parts += len(vals) - len(parts)
            if not parts:
                empty_rows += 1
                continue
            line = sep.join(parts)
        else:
            if any(not v for v in vals):
                empty_rows += 1
                continue
            line = sep.join(vals)
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return {"lines": lines, "空行丢弃": empty_rows, "空级别跳过": skipped_parts, "重复去重": len(rows) - empty_rows - len(lines)}


def _read_rows(path: Path) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(path, dtype=str)
    df = df.where(df.notnull(), "")  # NaN → ""
    df.columns = [_norm(str(c)) for c in df.columns]
    return df.to_dict("records")


# ═══════════════════════════════════════════════════
# 路由：页面
# ═══════════════════════════════════════════════════
@pages.get("/category", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent.parent / "pages" / "category.html").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════
# 路由：上传 → 列清单
# ═══════════════════════════════════════════════════
@router.post("/upload")
async def upload(file: UploadFile):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "只收 xlsx/xls")
    file_id = __import__("uuid").uuid4().hex[:12]
    path = CATEGORY_DIRS["third"].parent.parent / "web" / "uploads" / f"{file_id}.xlsx"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(await file.read())
    df = __import__("pandas").read_excel(path, dtype=str, nrows=0)
    return {"file_id": file_id, "filename": file.filename,
            "headers": [_norm(str(c)) for c in df.columns]}


# ═══════════════════════════════════════════════════
# 路由：预览（不落盘）
# ═══════════════════════════════════════════════════
class PreviewReq(BaseModel):
    file_id: str
    cols: list[str]          # 按层级顺序
    sep: str = " > "
    skip_empty: bool = True


@router.post("/preview")
def preview(req: PreviewReq):
    excel = _upload_path(req.file_id)
    if not req.cols:
        raise HTTPException(400, "至少选一列")
    if "," in req.sep:
        raise HTTPException(400, "分隔符不能含逗号（单列 CSV 会被 pandas 劈列，下游读丢数据）")
    rows = _read_rows(excel)
    missing = [c for c in req.cols if c not in rows[0].keys()] if rows else req.cols
    if missing:
        raise HTTPException(400, f"列不存在: {missing}")
    out = convert(rows, req.cols, req.sep, req.skip_empty)
    return {"total_rows": len(rows), "out_rows": len(out["lines"]),
            "stats": {k: v for k, v in out.items() if k != "lines"},
            "preview_lines": out["lines"][:20]}


# ═══════════════════════════════════════════════════
# 路由：落盘
# ═══════════════════════════════════════════════════
class SaveReq(PreviewReq):
    category_type: str          # third / general
    filename: str
    header: str = "前台类目"


@router.post("/save")
def save(req: SaveReq):
    excel = _upload_path(req.file_id)
    target_dir = _dir_of(req.category_type)
    target_dir.mkdir(parents=True, exist_ok=True)

    if not _SAFE_NAME.match(req.filename):
        raise HTTPException(400, "文件名只允许中文/字母/数字/下划线/连字符 + .csv")
    if "," in req.sep:
        raise HTTPException(400, "分隔符不能含逗号")

    out = convert(_read_rows(excel), req.cols, req.sep, req.skip_empty)
    old_rows = None
    target = target_dir / req.filename
    if target.exists():
        old_rows = len(target.read_text(encoding="utf-8-sig").splitlines()) - 1

    # UTF-8 BOM + CRLF（下游 _load_categories 的现役格式）
    content = req.header + "\r\n" + "\r\n".join(out["lines"]) + "\r\n"
    target.write_text(content, encoding="utf-8-sig", newline="")

    return {"saved": str(target), "rows": len(out["lines"]), "old_rows": old_rows,
            "stats": {k: v for k, v in out.items() if k != "lines"}}


# ═══════════════════════════════════════════════════
# 路由：文件管理（列表 + 删除）
# ═══════════════════════════════════════════════════
@router.get("/files")
def list_files(category_type: str):
    d = _dir_of(category_type)
    active = _active_file(category_type)
    files = []
    if d.exists():
        for f in sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            rows = max(0, len(f.read_text(encoding="utf-8-sig").splitlines()) - 1)
            files.append({
                "name": f.name, "rows": rows,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M"),
                "active": str(f) == str(active),
            })
    return {"files": files}


@router.delete("/files")
def delete_file(category_type: str, name: str):
    d = _dir_of(category_type)
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "非法文件名")
    target = d / name
    if not target.exists():
        raise HTTPException(404, "文件不存在")
    active = _active_file(category_type)
    if str(target.resolve()) == str(active.resolve()):
        raise HTTPException(400, "生效中的文件不能删——先在 config.py 换指向再删")
    target.unlink()
    return {"deleted": name}


def _upload_path(file_id: str) -> Path:
    p = ROOT / "web" / "uploads" / f"{file_id}.xlsx"
    if not p.exists():
        raise HTTPException(404, "上传文件已过期，重新上传")
    return p
