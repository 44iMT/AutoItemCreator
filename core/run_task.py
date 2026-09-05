"""
参数化任务执行器：吃 --config task.json，web 执行页 / 外部调用的统一入口

定位（与 tasks/ 手动脚本的分工）：
- tasks/*.py  = 手动世界，路径写死、f-string 拼 prompt，直接 python 跑
- 本文件     = 配置驱动，task.json 即任务快照（跑完留档：哪张表、哪版 prompt、什么参数）

task.json 字段（全部必填项缺失即启动报错，不裸跑半配置任务）：
{
  "input_file":  "web/uploads/xxx.xlsx",        # 输入表
  "output_file": "web/uploads/xxx-结果.xlsx",   # 输出表
  "columns_map": {"商品编码": "商品编码", ...},   # 输入列 → 展示名
  "out_columns": {"前台类目": "说明", ...},       # 结果键 → 模板说明
  "system_prompt": "…{{类目表}}…",              # 模板；占位符由 injections 结果替换
  "tools": ["search_products", "search_by_barcode", "web_search"],  # 按名挂载
  "category": {"third": "data/third_category/三方类目902.csv"},     # 类目表槽位（可选）
  "injections": {"{{类目表}}": {"tool": "get_third_categories", "intro": "三方类目已直接附在下方参考区：\n\n"}},
  "concurrency": 4, "retry_times": 3, "include_input": true,
  "log_tag": "ReCategory",
  "reuse": {"collection": "recategory_cache_902", "exact_fields": ["商品编码"],
            "vector_fields": ["商品名称"], "vector_threshold": 0.95}
}
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import build_agent, run_excel_task
from tools import select_category_files
from tools.web_search import web_search
from tools.search import search_products
from tools.barcode import search_by_barcode
from tools.category import get_categories, get_third_categories

# 工具注册表：task.json 里按名挂载。新增工具在此登记一行
TOOL_REGISTRY = {
    "search_products": search_products,
    "search_by_barcode": search_by_barcode,
    "web_search": web_search,
    "get_categories": get_categories,
    "get_third_categories": get_third_categories,
}

REQUIRED_KEYS = ["input_file", "output_file", "columns_map", "out_columns",
                 "system_prompt", "tools"]


def compose_system_prompt(template: str, injections: dict) -> str:
    """注入：执行只读工具 → 结果替换占位符。占位符缺工具或执行失败 → 启动即炸，不裸跑。"""
    prompt = template
    for slot, inj in (injections or {}).items():
        tool_name = inj.get("tool")
        if tool_name not in TOOL_REGISTRY:
            raise ValueError(f"注入的工具未注册: {tool_name}")
        result = TOOL_REGISTRY[tool_name](**inj.get("params", {}))
        prompt = prompt.replace(slot, result)  # replace 而非 format：prompt 里有裸 {}；老快照的 intro 字段被忽略
    # 占位符没被任何注入覆盖 → 残着 {{xxx}} 裸跑必错
    if "{{" in prompt:
        leftover = [s.split("}}")[0] for s in prompt.split("{{")[1:]]
        raise ValueError(f"模板占位符未被注入覆盖: {leftover[:3]}")
    return prompt


def main():
    parser = argparse.ArgumentParser(description="配置驱动的 Excel 批处理执行器")
    parser.add_argument("--config", required=True, help="task.json 路径")
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    # tools 允许空列表（无工具纯 LLM 任务），其余字段空值即缺
    missing = [k for k in REQUIRED_KEYS if k != "tools" and not cfg.get(k)]
    if cfg.get("tools") is None:
        missing.append("tools")
    if missing:
        raise SystemExit(f"task.json 缺必填字段: {missing}")

    # 1. 类目表槽位：选了就用任务的，不选走 config 默认
    category = cfg.get("category") or {}
    if category.get("third") or category.get("general"):
        select_category_files(third=category.get("third"), general=category.get("general"))
        print(f"[run_task] 类目表: {category}")

    # 2. prompt 注入（占位符 → 工具结果）；失败即炸不降级
    system_prompt = compose_system_prompt(cfg["system_prompt"], cfg.get("injections"))
    print(f"[run_task] system_prompt 就绪: {len(system_prompt)} 字符")

    # 3. 按名挂载工具
    unknown = [t for t in cfg["tools"] if t not in TOOL_REGISTRY]
    if unknown:
        raise SystemExit(f"未注册的工具: {unknown}")
    tools = [TOOL_REGISTRY[t] for t in cfg["tools"]]

    agent = build_agent(tools, system_prompt=system_prompt)

    # 4. 跑批（参数与 run_excel_task 一一对应）
    run_excel_task(
        agent,
        input_file=cfg["input_file"],
        output_file=cfg["output_file"],
        columns_map=cfg["columns_map"],
        out_columns=cfg["out_columns"],
        concurrency=cfg.get("concurrency", 4),
        retry_times=cfg.get("retry_times", 3),
        include_input=cfg.get("include_input", True),
        display_key=cfg.get("display_key"),
        display_out_key=cfg.get("display_out_key"),
        log_tag=cfg.get("log_tag", "Task"),
        reuse=cfg.get("reuse"),
    )


if __name__ == "__main__":
    main()
