"""
公共底座：Agent 构建 + Excel 批量任务执行器

tasks/ 下的各任务只负责声明配置（字段映射、输出列、prompt），
读表 → 并发调用 agent → JSON 提取 → 重试 → 保序写表 全在这里统一处理。

统一修复（相对旧 tasks 里的内联版）：
- 失败行不再静默蒸发：重试耗尽后保留原字段、结果列留空，行数守恒
- LLM 漏回显输入字段时回退用原值，不再被空串覆盖
- JSON 提取前把中文引号 / 尾逗号这类常见脏字符兜住
"""
import json
import re
import time

import json5
import pandas as pd
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import DEEPSEEK_KEY, DEEPSEEK_BASE_URL

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_CONCURRENCY = 4
DEFAULT_RETRY_TIMES = 3


# ═══════════════════════════════════════════════════
# Agent 构建
# ═══════════════════════════════════════════════════
def build_agent(tools, system_prompt, model=DEFAULT_MODEL, temperature=0, **kwargs):
    """LLM + create_agent 一把梭，tasks 里一行构建。"""
    llm = ChatOpenAI(
        model=model,
        api_key=DEEPSEEK_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
    )
    return create_agent(llm, tools, system_prompt=system_prompt, **kwargs)


# ═══════════════════════════════════════════════════
# JSON 提取
# ═══════════════════════════════════════════        ═
def extract_json(text: str) -> dict:
    """
    从 LLM 回复中提取最外层 {} 并解析成 dict。

    - 模型偶尔在 JSON 前后加"好的"/解释文字，只取第一个配平的 {...}
    - 配平失败的退化为 s..end 的裸截断
    - 解析前清洗中文引号、尾逗号等常见脏字符
    - 返回值保证是 dict（模型返回 [..] 时取第一个 dict 元素）
    """
    s = text.find("{")
    if s < 0:
        raise ValueError("回复中没有 '{'")
    d, e = 1, s + 1
    while d > 0 and e < len(text):
        if text[e] == "{":
            d += 1
        elif text[e] == "}":
            d -= 1
        e += 1
    if d != 0:  # 配平失败，退化截到文本末尾
        e = len(text)
    candidate = text[s:e]

    # 常见脏字符：中文引号 → 英文引号（只在成对键值场景安全替换键名引号）
    cleaned = candidate.replace("“", '"').replace("”", '"')
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)  # 尾逗号

    out = json5.loads(cleaned)
    if isinstance(out, list):
        out = next((x for x in out if isinstance(x, dict)), {})
    if not isinstance(out, dict):
        raise ValueError(f"解析结果不是对象: {type(out)}")
    return out


# ═══════════════════════════════════════════════════
# Excel 批量任务执行器
# ═══════════════════════════════════════════════════
def run_excel_task(
    agent,
    input_file: str,
    output_file: str,
    columns_map: dict,
    out_columns: dict,
    concurrency: int = DEFAULT_CONCURRENCY,
    retry_times: int = DEFAULT_RETRY_TIMES,
    include_input: bool = False,
    prompt_prefix: str = "",
    display_key: str = None,
    display_out_key: str = None,
    log_tag: str = "agent",
    callback=None,
):
    """
    读 Excel → 并发调 agent → 提取 JSON → 按原序写回 Excel。

    参数
    ----
    columns_map    : {输入列名: 展示名}，取输入字段拼 prompt
    out_columns    : {结果键: 模板说明}，键即输出列名，值仅用于拼 JSON 模板提示
    include_input  : False=只输出结果列；True=原始输入列 + 结果列
    prompt_prefix  : prompt 里字段清单前的引导语
    display_key    : 进度日志里显示的输入字段（默认取 columns_map 第一个值）
    display_out_key: 进度日志里显示的结果字段（默认取 out_columns 第一个键）
    callback       : 每行成功后的回调 (i, fields, out) -> None，可做额外打印
    """
    rows = pd.read_excel(input_file, dtype=str).to_dict("records")
    print(f"[{log_tag}] 读取 '{input_file}'，{len(rows)} 行，并发={concurrency}")

    out_keys = list(out_columns.keys())
    json_template = "{\n" + "\n".join(f'  "{k}": "{v}"' for k, v in out_columns.items()) + "\n}"
    display_key = display_key or next(iter(columns_map.values()))  # 默认第一个展示名
    display_out_key = display_out_key or out_keys[0]
    display_key = display_key if display_key in columns_map.values() else next(iter(columns_map.values()))

    def process_one(i, row):
        # fields 以展示名（columns_map 的值）为键，与输出表头/日志字段一致
        fields = {
            label: row[k]
            for k, label in columns_map.items()
            if k in row and row[k] not in ("nan", "None", "")
        }
        lines = "\n".join(f"- {label}: {value}" for label, value in fields.items())
        prompt = f"""{prompt_prefix}

{lines}

只输出JSON，不要markdown包裹：
{json_template}
"""
        last_err = None
        for attempt in (range(retry_times)):
            try:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=prompt)]},
                    {"configurable": {"thread_id": f"item-{i + 1}"}},
                )
                out = extract_json(result["messages"][-1].content)

                # 结果字段合并：LLM 漏回显输入字段 → 回退原值，避免被空串覆盖
                merged = {**fields}
                for k in out_keys:
                    v = out.get(k)
                    if v in (None, ""):
                        # 漏回显的输入字段（columns_map 值与输出键同名时）用原值兜底
                        origin = columns_map.get(k)
                        v = row.get(origin, "") if origin else ""
                    merged[k] = v if v is not None else ""
                merged["_idx"] = i

                print(
                    f"[{log_tag}] [{i + 1}/{len(rows)}] "
                    f"{fields.get(display_key, '?')} → {merged.get(display_out_key, '?')}"
                )
                if callback:
                    callback(i, fields, out)
                return merged
            except Exception as e:
                last_err = e
                if attempt < retry_times - 1:
                    time.sleep(2 ** attempt)

        # 失败保行：保留原字段、结果列留空，行数守恒
        print(
            f"[{log_tag}] [{i + 1}/{len(rows)}] {fields.get(display_key, '?')} "
            f"重试{retry_times}次仍失败: {last_err}"
        )
        failed = {**fields}
        for k in out_keys:
            failed[k] = ""
        failed["_idx"] = i
        return failed

    # 并发执行
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process_one, i, row): i for i, row in enumerate(rows)}
        for f in as_completed(futures):
            results.append(f.result())

    # 按原始顺序排列
    results.sort(key=lambda r: r["_idx"])
    failed_rows = [r for r in results if not any(str(r.get(k, "")) for k in out_keys)]
    if failed_rows:
        print(f"[{log_tag}] ⚠ {len(failed_rows)} 行重试耗尽仍失败，已保留空结果：")
        for r in failed_rows:
            print(f"  - {r.get(display_key, '?')}")
    print(f"[{log_tag}] 完成 {len(results)}/{len(rows)} 行")

    # 保存（结果列全空串时 pandas 的 to_excel 会把整行丢掉，换成 NaN 写入占位）
    if include_input:
        input_headers = list(dict.fromkeys(v for k, v in columns_map.items()))
        headers = input_headers + out_keys
    else:
        headers = out_keys
    out_df = pd.DataFrame(
        # 结果列空值写 None（真空单元格）；xlsxwriter 会整行丢弃，必须用 openpyxl
        [[r.get(h) if r.get(h) not in (None, "") else None for h in headers] for r in results],
        columns=headers,
    )
    out_df.to_excel(output_file, index=False, engine="openpyxl")
    print(f"[{log_tag}] 完成 → '{output_file}'")
    return results


__all__ = ["build_agent", "extract_json", "run_excel_task"]
