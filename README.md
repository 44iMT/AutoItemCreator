# AutoItemCreator

门店商品 Excel → AI 检索总部商品库 → 匹配/标准化/归类 → 结果 Excel。

一条龙工作台：**Web 控制台**（日常）+ **CLI 脚本**（兜底）双入口，同一套引擎。

```
桌面双击 AutoItemCreator.lnk
  → Web 控制台（Edge app 窗口）
      ① 主档商品库构建   上传总部商品导出 → 字段映射 → 一键建向量库
      ② 类目表转换       商家类目 xlsx → csv 白名单（三方/通用分目录）
      ③ 商品数据构建     上传门店表 → 选预设/全参数配置 → 跑批 → 下载结果
  → 停止/断点续跑/刷新恢复，全程实时日志
```

## 项目结构

```
config.example.py   配置模板（复制为 config.py 填入密钥；config.py 不入库）
requirements.txt    Python 依赖

desktop.py          桌面壳：起服务 → Edge --app 窗口（图标=favicon，几何居中）→ 心跳守护
AutoItemCreator.lnk 桌面快捷方式（直连 venv 的 pythonw，零控制台黑框）

web/                Web 控制台（FastAPI，页面即领域）
  app.py            组装层：static / favicon / 首页 / 路由注册 / 启动清场
  common.py         共享：Jinja2 渲染器 / _norm 表头归一 / 子进程 worker 协议
  pages/            base.html（侧边栏+深色token 唯一定义）+ 四个页面
  routers/          build / category / run 三个领域（页面路由 + /api/<域>/* 私有 API）

core/               引擎层（web 与 CLI 共用）
  agent.py          Agent 底座：构建 agent + Excel 批量任务执行器
  run_task.py       配置驱动执行器：--config task.json（web 执行页的后端）
  builder.py        总部商品入库：Excel → 清洗 → 向量嵌入 → Qdrant
  reuse.py          结果复用缓存：Qdrant 双模式（精确/向量）检索

tasks/              CLI 手动世界（零改动保留）
  _template.py      调用模板：历史任务配置，取消注释即用
  recategory.py     类目补全：为门店商品匹配三方前台类目

tools/              Agent 工具
  search.py         向量语义搜索（BGE 嵌入 + 重排）
  barcode.py        条码精确匹配
  web_search.py     DeepSeek 联网搜索
  category.py       类目表读取（select_category_files 任务级选表）

data/               运行时数据（不入库）
  category/         通用类目 csv（类目页管理）
  third_category/   三方类目 csv（902 现役）
  presets/          任务预设（如 归类-recategory.json，一键满配）
  runs/             每次执行的 task.json 快照（审计留档）
  logs/             桌面壳日志（pythonw 态 stdout 落盘处）
  edge_profile/     Edge app 窗口独立 profile（几何归参数管的代价）
```

## 快速开始

### 环境

```bash
pip install -r requirements.txt
copy config.example.py config.py   # 填入 DEEPSEEK_KEY / SILICONFLOW_KEY
```

Qdrant 本地运行在 `http://localhost:6333`（[Docker](https://qdrant.tech/documentation/guides/install/) 或二进制均可）。

### 日常：Web 控制台

```bash
python desktop.py        # 或双击桌面快捷方式
```

窗口即开（Edge app 模式，随机端口）。三页用法见首页流程卡：
**建范本库（偶尔）→ 备类目表（商家改版时）→ 日常跑批**。

跑批支持：预设一键满配 / 全参数手调（列映射、输出列、工具、注入、缓存）/
中途停止 / 断点续跑 / 刷新自动恢复日志流。

### 兜底：CLI 脚本

```bash
python core/run_task.py --config <task.json>   # 配置驱动执行器（同 web 后端）
python tasks/recategory.py                     # 手动脚本（路径写死，直接跑）
python core/builder.py                         # 建库（web 构建页的同款引擎）
```

Web 与 CLI 是同一引擎的两个入口；DeepSeek 抖掉的日子，CLI 永远可用。

## 执行器（core/run_task.py）

吃一份 `task.json` 跑一个任务——它既是配置也是快照（web 每次执行都会在
`data/runs/` 留档，日后"这批结果什么配置跑的"查文件）：

```jsonc
{
  "input_file": "门店表.xlsx",
  "output_file": "结果.xlsx",
  "columns_map": {"商品编码": "商品编码", "商品名称": "商品名称"},  // 进每行 prompt 的字段
  "out_columns": {"前台类目": "字段说明（拼进 JSON 模板）"},        // 输出列契约
  "system_prompt": "…{{类目表}}…",   // 模板；{{占位符}} 由注入替换
  "tools": ["search_products", "search_by_barcode", "web_search"],
  "category": {"third": "data/third_category/三方类目902.csv"},     // 类目表槽位
  "injections": {"{{类目表}}": {"tool": "get_third_categories"}},   // 启动时执行工具并替换
  "concurrency": 4, "retry_times": 3, "include_input": true,
  "reuse": {"collection": "recategory_cache_902", "exact_fields": ["商品编码"],
             "vector_fields": ["商品名称"], "vector_threshold": 0.95}
}
```

关键设计：

- **注入**：静态知识（类目表等）在启动时由只读工具执行并缝进 system prompt，
  失败即炸不裸跑——残着占位符的 prompt 一行都不该跑
- **类目槽位**：`select_category_files()` 任务级选表，不调用则走 config 默认；
  读取日志自带表名（`三方类目 ← 三方类目902.csv: 245 个`），跑批日志自证版本
- **工具白名单**：按名挂载，未注册即拒；空列表 = 无工具纯 LLM 任务（合法形态）

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

## 结果复用缓存

`reuse` 参数开启：跑过的行不再调 Agent，直接复用历史结果。三层瀑布——
精确缓存命中 → 向量缓存命中 → Agent（跑完入缓存）。全 Qdrant 单存储。

```python
REUSE = {
    "collection": "recategory_cache_902",  # 大改 prompt/类目表就换名（版本即名字）
    "exact_fields": ["商品编码"],       # 精确键：断点续跑
    "vector_fields": ["商品名称"],      # 向量键：跨批次相似复用
    "vector_threshold": 0.95,          # 开了 vector_fields 必填——阈值是业务决策
    # "rebuild": True,                 # 启动时删库重建，默认 False
}
```

两层职责不同：**精确层管断点续跑**（同一批数据重跑时认出"这行跑过"，
key 只取行内容字段，绝不含行号/文件名），**向量层管跨批次复用**
（下个月的新批里有这个月处理过的相似商品，嵌入相似度过阈值即复用）。

行为规则：

- 命中结果直接当 LLM 的 `out` 走后续 merge/写表，与 Agent 路径行为完全一致
- 只有 Agent 真跑的行入缓存，缓存命中的行不回写（相似误判不固化成精确事实）
- 失败行永不入缓存；逐行成功即写，跑到一半崩了重跑只补尾巴
- 查/存双向 best-effort：缓存故障只降级为走 Agent，不拖死批处理
- 进度日志标注来源 `[精确缓存]` / `[向量缓存 0.97]`，收尾报各层命中数

向量层注意：同名不同规格的商品相似度可能很高，`vector_fields` 建议控制在
1-2 个（商品名称+规格顶天）；阈值定多少，跑一批看 `[向量缓存 分数]` 的分布再校。

## 工具

| 工具 | 用途 |
|------|------|
| `search_by_barcode` | Qdrant payload 精确匹配条码 |
| `search_products` | 向量语义搜索 + BGE 重排 |
| `web_search` | DeepSeek 联网搜索 |
| `get_categories` | 返回全部通用前台类目 |
| `get_third_categories` | 返回全部三方前台类目 |

## 架构

每个商品独立 Agent 对话（独立 thread_id），多线程并发执行，上下文不膨胀。
开启 `reuse` 时每行先查结果复用缓存，命中即出、未命中走 Agent 并入缓存。

```
pandas 读 Excel → 每行先查复用缓存 ──命中──→ 直接出结果
                     │ 未命中                     ↑
                     ↓                           │ 成功后入缓存（逐行即写）
                   每行一个 Agent 调 ─────────────┘
                     ├ 条码搜索
                     ├ 向量搜索
                     ├ 联网搜索
                     └ 类目查询
```

Web 层架构：页面即领域（每页一个 router：页面路由 + `/api/<域>/*` 私有 API +
自身任务闸）；长任务（建库/跑批）走 subprocess 隔离，日志经 SSE 实时回流，
浏览器刷新自动重连续传。

### 架构决策

这个架构经历了 LLM+RAG → Agent → 上下文压缩 → 行间隔离 → Web 化的完整演进。
踩过的坑和收敛的经验记录在 [`经验总结-Agent批处理架构演进.md`](./经验总结-Agent批处理架构演进.md)。

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | DeepSeek V4 Flash |
| Agent | LangGraph create_agent |
| Web | FastAPI + Jinja2 + SSE（Edge --app 桌面壳） |
| 向量库 | Qdrant（本地 localhost:6333） |
| 嵌入 | BAAI/bge-large-zh-v1.5（SiliconFlow, 1024维） |
| 重排 | BAAI/bge-reranker-v2-m3（SiliconFlow） |
| 解析 | pandas + json5 |

## 相关文章

- [Agent 批处理中上下文压缩为何失败](https://blog.csdn.net/AELimit/article/details/163190245)
- [给 Agent 的工具加了默认参数，它反而更笨了](https://blog.csdn.net/AELimit/article/details/163190791)
- [从 LLM-only 到 Agent：一个商超项目的架构选型](https://blog.csdn.net/AELimit/article/details/163208331)
