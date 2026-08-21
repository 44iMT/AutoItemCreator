# AutoItemCreator

门店新品 Excel → AI 搜索总部商品库 → 匹配/标准化 → 输出结果 Excel。

## 项目结构

```
config.example.py   配置模板（复制为 config.py 填入密钥）
config.py            实际配置（gitignore，不提交）
requirements.txt     Python 依赖

core/                基础设施包
  agent.py           Agent 底座：构建 agent + Excel 批量任务执行器
  builder.py         总部商品入库：Excel → 向量嵌入 → Qdrant

tasks/
  _template.py       调用模板：四个历史任务的完整配置，取消注释即用
  recategory.py      类目补全：为门店商品匹配三方前台类目

tools/
  search.py          向量语义搜索（BGE 嵌入 + 重排）
  barcode.py         条码精确匹配
  web_search.py      DeepSeek 联网搜索
  category.py        类目列表（通用类目 / 三方类目）

data/
  通用类目.csv         前台类目数据
  三方类目.csv         第三方平台前台类目（含一级独占行）
```

## 工作方式

任务 = 纯配置 + 一行调用。公共底座（`core/agent.py` 的 `run_excel_task`）
统一处理读表、并发、重试、失败保行、JSON 提取、写表：

```python
from core import build_agent, run_excel_task
from tools import search_products, search_by_barcode, get_third_categories, web_search

agent = build_agent(
    [search_products, search_by_barcode, get_third_categories, web_search],
    system_prompt="...",
)

run_excel_task(
    agent,
    input_file=INPUT_FILE,
    output_file=OUTPUT_FILE,
    columns_map=COLUMNS_MAP,     # 输入映射：Excel列名 → 提示词显示名
    out_columns=OUT_COLUMNS,     # 输出定义：字段名 → 描述（拼进 JSON 模板）
    concurrency=4,
    retry_times=3,
    include_input=False,         # False=只输出结果列；True=原始列+结果列
    display_key="商品名称",      # 进度日志显示字段
    log_tag="category",
)
```

新任务直接复制 `tasks/recategory.py` 或 `tasks/_template.py` 改配置即可。

### 底座保证

- 失败行不蒸发：重试耗尽后保留原字段、结果列留空，行数守恒
- LLM 漏回显输入字段时回退原值，不被空串覆盖
- JSON 提取兜底：花括号截取、中文引号、尾逗号、markdown 包裹
- 写表用 openpyxl 引擎，全空结果行不会被吞掉

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | DeepSeek V4 Flash |
| Agent | LangGraph create_agent |
| 向量库 | Qdrant（本地 localhost:6333） |
| 嵌入 | BAAI/bge-large-zh-v1.5（SiliconFlow, 1024维） |
| 重排 | BAAI/bge-reranker-v2-m3（SiliconFlow） |
| 解析 | pandas + json5 |

## 快速开始

### 环境

```bash
pip install -r requirements.txt
```

Qdrant 本地运行在 `http://localhost:6333`。

### 1. 构建向量索引

把总部商品 Excel 导入 Qdrant，数据更新时重跑：

```bash
python core/builder.py
```

### 2. 改配置

打开要跑的任务，改顶部变量：

```python
INPUT_FILE  = r"门店新品.xlsx"    # 输入文件
OUTPUT_FILE = r"结果.xlsx"         # 输出文件
CONCURRENCY = 4                    # 并发数
RETRY_TIMES = 3                    # 重试次数

COLUMNS_MAP = {                    # 输入映射：Excel列名 → 提示词显示名
    "商品条码": "商品条码",
    "商品名称": "商品名称",
    # Excel 中没有的列自动跳过，不放进提示词
}
OUT_COLUMNS = {                    # 输出定义：字段名 → 描述（详见下节）
    "前台类目": "根据范本和搜索生成的类目",
    ...
}
```

### 3. 运行

```bash
python tasks/recategory.py   # 类目补全
```

## OUT_COLUMNS：输出即提示词

`OUT_COLUMNS` 看着只是"输出列定义"，实际上身兼四职，是这套架构里任务设计的核心杠杆：

| 身份 | 说明 |
|------|------|
| **输出契约** | 键 = 结果 Excel 的列名，跑完表长什么样它说了算 |
| **JSON 模板** | 底座把 `{键: 描述}` 拼成填空模板塞进每行提示词尾部，模型照着填空 |
| **填空说明** | 描述就是给模型看的字段级指令——写什么口径、受什么约束、找不到怎么办 |
| **任务设计空间** | 加一个键 = 长出一个新输出维度，一行描述就能解锁一类新能力 |

### 机制：一行配置去哪了

底座（`core/agent.py`）把 `OUT_COLUMNS` 拼进每行提示词：

```
OUT_COLUMNS = {"前台类目": "根据范本和搜索生成的类目", ...}

          ↓ 拼成

只输出JSON，不要markdown包裹：
{
  "前台类目": "根据范本和搜索生成的类目",
  ...
}
```

所以 system_prompt 里**不用**逐字段教格式，只需讲清判断逻辑；
字段级的"怎么填"全部放在描述里，两处各司其职、互不重复。

### 心法：描述的四个信息点

好的描述 = 口径 + 约束 + 兜底 + 格式，一句话给足密度：

```python
# ✅ 好的写法
"相似程度": "商品信息相似程度，百分数表示，完全一样为100%",   # 口径+格式+基准
"异常标记": "规格异常/无匹配/无",                              # 枚举约束
"总部商品编码": "总部系统中的商品编码，未找到则为空字符串",      # 兜底指令

# ❌ 差的写法（模型只能瞎猜口径）
"相似程度": "相似度"
```

### 实战：加一个字段 = 解锁一类新任务

`recategory.py` 的类目建议字段——三方类目白名单覆盖不全时，一行描述就给了
agent "白名单外自由发挥"的授权，顺便产出一份"该向平台提的新类目需求清单"：

```python
OUT_COLUMNS = {
    "前台类目": "根据范本和搜索生成的前台类目",
    "类目建议": "建议增添的前台类目名称",   # ← 白名单里没有合适的时才填
}
```

配套的 system_prompt 只需补一句判断逻辑："如果三方类目中没有符合的类目，
就把你认为合适的类目放在类目建议中"。

同理可以长出：枚举审核（"合规/待审/违规"）、置信度分级（"高/中/低"）、
多值标签（"用顿号分隔"）……字段描述本身就是 prompt 工程的一部分。

## 工具

| 工具 | 用途 |
|------|------|
| `search_by_barcode` | Qdrant payload 精确匹配条码 |
| `search_products` | 向量语义搜索 + BGE 重排 |
| `web_search` | DeepSeek 联网搜索 |
| `get_categories` | 返回全部通用前台类目 |
| `get_third_categories` | 返回全部三方前台类目（含一级独占行） |

## 架构

每个商品独立 Agent 对话（独立 thread_id），多线程并发执行，上下文不膨胀。

```
pandas 读 Excel → 每行一个 Agent 调  → 收集结果 → pandas 写 Excel
                    ├ 条码搜索
                    ├ 向量搜索
                    ├ 联网搜索
                    └ 类目查询
```

## 架构决策

这个架构不是一步到位的，经历了 LLM+RAG → Agent → 上下文压缩 → 行间隔离 的完整演进。踩过的坑和收敛的经验记录在 [`经验总结-Agent批处理架构演进.md`](./经验总结-Agent批处理架构演进.md)。

## 相关文章

- [Agent 批处理中上下文压缩为何失败](https://blog.csdn.net/AELimit/article/details/163190245)
- [给 Agent 的工具加了默认参数，它反而更笨了](https://blog.csdn.net/AELimit/article/details/163190791)
- [从 LLM-only 到 Agent：一个商超项目的架构选型](https://blog.csdn.net/AELimit/article/details/163208331)
