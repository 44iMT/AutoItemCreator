"""
获取所有前台类目
"""
from config import CATEGORY_FILE, THIRD_CATEGORY_FILE


def _load_categories(path: str, header: str) -> list:
    import pandas as pd
    df = pd.read_csv(path, dtype=str, header=0)
    categories = df.iloc[:, 0].dropna().tolist()
    # 过滤掉表头行（如果被当成数据的话）
    return [c for c in categories if c != header and c.strip()]


def get_categories() -> str:
    """返回所有前台类目列表，用于给门店商品分类时参考。"""
    categories = _load_categories(CATEGORY_FILE, "通用类目")
    print(f"[category] 读取 {len(categories)} 个类目")
    return "\n".join(categories)


def get_third_categories() -> str:
    """返回所有第三方前台类目列表（含一级独占行），用于给第三方平台商品分类时参考。"""
    categories = _load_categories(THIRD_CATEGORY_FILE, "第三方类目")
    print(f"[category] 读取 {len(categories)} 个第三方类目")
    return "\n".join(categories)
