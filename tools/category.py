"""
获取所有前台类目

类目表选择：模块级槽位 + select_category_files()。
- 任务启动前调用 select_category_files(third=..., general=...) → 用指定表（web 执行页等场景）
- 不调用 → get_xxx() 走 config 默认路径（手动脚本世界，零改动）
单机单任务进程用；槽位即扩展点，将来有第三张表并存的场景加一个参数即可。
"""
import os

from config import CATEGORY_FILE, THIRD_CATEGORY_FILE

# 类目表槽位：None = 未选择，走 config 默认
_custom_third = None
_custom_general = None


def select_category_files(third: str = None, general: str = None):
    """任务启动前选自定义类目表；不调用则 get_xxx() 走 config 默认路径。

    只应在任务进程启动早期调用一次（如 run_task.py），别在常驻服务里反复切。
    """
    global _custom_third, _custom_general
    if third:
        _custom_third = third
    if general:
        _custom_general = general


def _load_categories(path: str) -> list:
    """读类目表：pandas 吃掉表头，剔空行/空白。（表均由 web 类目页生成，表头不再猜测过滤）"""
    import pandas as pd
    df = pd.read_csv(path, dtype=str, header=0)
    categories = df.iloc[:, 0].dropna().tolist()
    return [c for c in categories if c.strip()]


def _read(path: str, label: str) -> str:
    """读表 → 换行拼接。日志自带实际文件名：跑批日志自证本批用的哪张表。"""
    categories = _load_categories(path)
    print(f"[category] {label} ← {os.path.basename(path)}: {len(categories)} 个类目")
    return "\n".join(categories)


def get_categories() -> str:
    """返回所有前台类目列表，用于给门店商品分类时参考。"""
    return _read(_custom_general or CATEGORY_FILE, "通用类目")


def get_third_categories() -> str:
    """返回所有第三方前台类目列表（含一级独占行），用于给第三方平台商品分类时参考。"""
    return _read(_custom_third or THIRD_CATEGORY_FILE, "三方类目")
