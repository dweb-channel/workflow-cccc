# T170: LangGraph 工作流引擎深入教程

> 基于 work-flow 项目真实代码，讲解 LangGraph StateGraph 的声明式构建、条件路由、循环控制、状态管理，以及项目中的真实踩坑案例。
>
> **前置阅读**：建议先完成 [T164 项目架构全景](./t164-architecture-overview.md) 和 [T165 Claude API + Prompt](./t165-claude-api-prompt.md)，本文聚焦架构图中间层的「LangGraph 执行引擎」。

---

## 目录

- [S1: StateGraph 构建全流程](#s1-stategraph-构建全流程)
  - [1.1 声明式三件套：NodeConfig / EdgeDefinition / WorkflowDefinition](#11-声明式三件套nodeconfigedgedefinitionworkflowdefinition)
  - [1.2 从定义到可执行图：build_graph_from_config()](#12-从定义到可执行图build_graph_from_config)
  - [1.3 node_func 闭包与状态合并](#13-node_func-闭包与状态合并)
  - [1.4 状态合并黑名单：为什么不用白名单](#14-状态合并黑名单为什么不用白名单)
  - [1.5 七步验证流水线：validate_workflow()](#15-七步验证流水线validate_workflow)
- [S2: 条件路由 + safe_eval 沙箱](#s2-条件路由--safe_eval-沙箱)
  - [2.1 ConditionNode：条件节点的执行逻辑](#21-conditionnode条件节点的执行逻辑)
  - [2.2 条件边如何驱动路由](#22-条件边如何驱动路由)
  - [2.3 safe_eval 沙箱：AST 白名单安全模型](#23-safe_eval-沙箱ast-白名单安全模型)
  - [2.4 路由函数的闭包构造](#24-路由函数的闭包构造)
  - [2.5 安全边界：什么能写，什么不能写](#25-安全边界什么能写什么不能写)
- [S3: 循环检测与运行时控制](#s3-循环检测与运行时控制)
  - [3.1 为什么需要循环](#31-为什么需要循环)
  - [3.2 DFS 环检测：detect_loops()](#32-dfs-环检测detect_loops)
  - [3.3 受控循环 vs 无出口环路](#33-受控循环-vs-无出口环路)
  - [3.4 运行时迭代控制：MaxIterationsExceeded](#34-运行时迭代控制maxiterationsexceeded)
  - [3.5 递归限制的计算公式](#35-递归限制的计算公式)
  - [3.6 真实案例：批量 Bug 修复的循环工作流](#36-真实案例批量-bug-修复的循环工作流)
- [S4: 节点注册表 + 动手练习](#s4-节点注册表--动手练习)
  - [4.1 策略模式：NODE_REGISTRY + NODE_CLASSES](#41-策略模式node_registry--node_classes)
  - [4.2 @register_node_type 装饰器](#42-register_node_type-装饰器)
  - [4.3 BaseNodeImpl 抽象基类](#43-basenodeimpl-抽象基类)
  - [4.4 现有节点类型一览](#44-现有节点类型一览)
  - [4.5 动手练习：构造 3 节点循环工作流](#45-动手练习构造-3-节点循环工作流)
- [关键文件索引](#关键文件索引)
- [踩坑集锦](#踩坑集锦)

---

## S1: StateGraph 构建全流程

### 1.1 声明式三件套：NodeConfig / EdgeDefinition / WorkflowDefinition

项目采用**声明式工作流定义** — 用数据结构描述"做什么"，而非编写命令式的图构建代码。这使得工作流可以序列化为 JSON、存入数据库、通过 API 传输。

三个核心 dataclass 定义在 `graph_builder.py:41-129`：

**NodeConfig（节点配置）**

```python
# graph_builder.py:41-61
@dataclass
class NodeConfig:
    id: str          # 唯一标识，如 "fetch_bug"
    type: str        # 节点类型，如 "llm_agent"（必须在注册表中注册）
    config: Dict[str, Any] = field(default_factory=dict)  # 节点特定配置
```

**EdgeDefinition（边定义）**

```python
# graph_builder.py:63-88
@dataclass
class EdgeDefinition:
    id: str                      # 唯一标识
    source: str                  # 源节点 ID
    target: str                  # 目标节点 ID（可以是 "__end__"）
    condition: Optional[str] = None  # 条件表达式（如 "has_more == True"）
```

注意 `__post_init__` 中的自环检测（L87-88）：

```python
if self.source == self.target:
    raise ValueError(f"self-loop detected: {self.source} -> {self.target}")
```

**WorkflowDefinition（工作流定义）**

```python
# graph_builder.py:96-129
@dataclass
class WorkflowDefinition:
    name: str
    nodes: List[NodeConfig]
    edges: List[EdgeDefinition]
    entry_point: Optional[str] = None      # 不填则自动检测
    max_iterations: int = 10               # 循环最大迭代次数
    merge_skip_keys: Optional[frozenset] = None  # 状态合并黑名单
```

`__post_init__` 做了大量预验证（L116-154）：
1. 自动把 `dict` 转为 dataclass（方便从 JSON 构造）
2. 检查节点/边 ID 唯一性
3. 验证边引用的节点存在
4. 自动检测入口点（无入边的节点）

**入口点自动检测逻辑**（L156-171）：

```python
def _detect_entry_point(self) -> str:
    node_ids = {node.id for node in self.nodes}
    target_ids = {edge.target for edge in self.edges if edge.target != END}
    entry_candidates = node_ids - target_ids  # 没有入边的节点
    # ...
```

> **设计哲学**：WorkflowDefinition 的 `__post_init__` 是"防御性编程"的典型 — 在数据进入系统的第一刻就做最大程度的验证，避免错误在后续流程中以更难理解的方式暴露。

---

### 1.2 从定义到可执行图：build_graph_from_config()

`build_graph_from_config()`（L598-712）是声明式定义到 LangGraph 可执行图的编译器。流程：

```
WorkflowDefinition
    ↓ validate_workflow()      ← 七步验证
    ↓ StateGraph(dict)         ← 创建空图（state 类型为 dict）
    ↓ 为每个 NodeConfig 创建节点实例 + node_func 闭包
    ↓ graph.add_node()         ← 注册到图中
    ↓ graph.set_entry_point()  ← 设置入口
    ↓ 按 source 分组处理边
    ↓   ├─ 有 condition → _add_conditional_edges()
    ↓   └─ 无 condition → graph.add_edge()
    ↓ graph.compile()          ← 编译为可执行图
    ↓
CompiledGraph（可用 astream/ainvoke 执行）
```

关键代码（L637-712）：

```python
# 创建 state graph，state 类型为 plain dict
graph = StateGraph(dict)

# 为每个节点创建实例 + 注册
for node_config in workflow.nodes:
    node = create_node(node_config.id, node_config.type, node_config.config)
    node_func = make_node_func(node)    # 闭包包装
    graph.add_node(node_config.id, node_func)

# 设置入口
graph.set_entry_point(workflow.entry_point)

# 按 source 分组处理边
for source_id, source_edges in edges_by_source.items():
    conditional_edges = [e for e in source_edges if e.condition]
    unconditional_edges = [e for e in source_edges if not e.condition]

    if conditional_edges:
        _add_conditional_edges(graph, source_id, ...)  # 条件路由
    else:
        for edge in unconditional_edges:
            graph.add_edge(source_id, edge.target)      # 普通边

return graph.compile()
```

> **注意**：`graph.compile()` 不再接受 `recursion_limit` 参数（LangGraph API 变更）。递归限制现在通过 `astream(state, config={"recursion_limit": N})` 在运行时传入（见 executor.py:114-115）。

---

### 1.3 node_func 闭包与状态合并

LangGraph 的节点函数签名是 `async def node_func(state: Dict) -> Dict`。项目用闭包将每个节点实例包装为这个签名：

```python
# graph_builder.py:650-669
def make_node_func(node_instance, _skip=skip_keys):
    async def node_func(state: Dict[str, Any]) -> Dict[str, Any]:
        # 1. 执行节点逻辑
        result = await node_instance.execute(state)

        # 2. 基础合并：把结果挂在 state[node_id] 下
        new_state = {**state, node_instance.node_id: result}

        # 3. 黑名单合并：把节点输出的非元数据字段提升到顶层
        if isinstance(result, dict):
            for key, value in result.items():
                if key not in _skip:
                    new_state[key] = value

        return new_state
    return node_func
```

这段代码做了两件事：

1. **命名空间挂载**：`new_state[node_id] = result` — 让下游可以通过 `state["node-1"]["field"]` 访问上游输出
2. **顶层状态提升**：把节点输出中的非元数据字段（如 `current_index`、`has_more`）直接合并到 `state` 顶层

> **为什么要闭包？** 因为 LangGraph 的 `add_node(name, func)` 要求一个纯函数，但我们需要保持对 `node_instance` 和 `skip_keys` 的引用。Python 闭包正好解决这个问题。

> **闭包陷阱提示**：注意 `_skip=skip_keys` 这个默认参数 — 这是经典的"循环变量捕获"防御。如果直接用 `skip_keys` 而不通过默认参数绑定，循环中所有闭包会共享同一个变量引用。

---

### 1.4 状态合并黑名单：为什么不用白名单

状态合并的策略经历了一次重要的设计变更：

```python
# graph_builder.py:91-93
_DEFAULT_MERGE_SKIP_KEYS = frozenset({
    "updated_fields", "error", "has_more", "node_id", "node_type",
})
```

**早期版本**使用白名单：

```python
# ❌ 旧版本（已废弃）
_MERGE_ALLOWED_KEYS = {"bugs", "current_index", "retry_count", "results"}
```

**问题**：白名单包含了业务字段名（`bugs`、`current_index`），导致引擎层和业务层耦合。当 Design-to-Spec 管线新增 `components`、`design_tokens` 等字段时，这些字段被白名单过滤掉，状态静默丢失。

**修复**：改为黑名单（L91-93），只排除已知的内部元数据字段。这样引擎层不需要知道业务字段名。

```python
# ✅ 当前版本
_DEFAULT_MERGE_SKIP_KEYS = frozenset({
    "updated_fields",  # UpdateStateNode 的内部追踪
    "error",           # 错误信息
    "has_more",        # 循环控制标志
    "node_id",         # 节点自身 ID
    "node_type",       # 节点类型标记
})
```

**WorkflowDefinition 支持自定义**：

```python
merge_skip_keys: Optional[frozenset] = None  # None → 使用默认黑名单
```

> **教训**：引擎层应该是**业务无关**的。如果你发现引擎代码里出现了业务字段名（如 `bugs`、`components`），这是一个架构异味。黑名单策略让引擎层只需要知道"什么不该合并"，而不需要知道"业务有哪些字段"。

---

### 1.5 七步验证流水线：validate_workflow()

`validate_workflow()`（L233-386）在构建图之前做全面检查，返回 `ValidationResult`（包含 errors 和 warnings）：

| 步骤 | 检查内容 | 严重级别 | 代码位置 |
|------|---------|---------|---------|
| 1 | 节点类型是否在注册表中 | error | L252-262 |
| 2 | 环检测（受控 vs 无出口） | error/warning | L264-294 |
| 3 | 节点配置是否合法 | error | L296-316 |
| 4 | 悬空节点（无入边也无出边） | warning | L318-331 |
| 5 | 无出边的节点（潜在死端） | warning | L333-347 |
| 6 | 条件表达式语法验证 | error | L349-362 |
| 7 | 同一节点的条件/非条件边混合 | warning | L364-383 |

注意 error 和 warning 的区别：
- **error** → `build_graph_from_config()` 会 `raise ValueError`，拒绝构建
- **warning** → 允许构建，但记录潜在问题

关键设计：步骤 2 的环检测会区分**受控循环**和**无出口环路**（详见 S3）。

---

## S2: 条件路由 + safe_eval 沙箱

### 2.1 ConditionNode：条件节点的执行逻辑

`ConditionNode`（`base.py:263-313`）是循环和分支的核心节点类型。它的 `execute` 方法很简单：

```python
# base.py:275-313
async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    condition_expr = self.config.get("condition", "")

    condition_result = bool(safe_eval(condition_expr, inputs))
    # 注：生产代码含 try/except SafeEvalError 降级处理
    # 表达式求值失败时 condition_result 默认为 False

    branch_taken = true_branch if condition_result else false_branch
    return {
        "branch_taken": branch_taken,
        "condition_result": condition_result,  # True 或 False
    }
```

`ConditionNode` 本身**只负责计算条件结果**，不负责路由。路由由 `_add_conditional_edges` 中的路由函数根据 `condition_result` 决定走哪条边。

---

### 2.2 条件边如何驱动路由

条件路由的完整数据流：

```
                          condition_expr
                               │
                               ▼
ConditionNode.execute(state) → {"condition_result": True/False}
                               │
                               ▼ （写入 state）
                               │
路由函数读取 state["condition_node_id"]["condition_result"]
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
           condition=True 的边     condition=False 的边
           (edge.condition =       (default / 另一条件)
           "condition_result
           == True")
```

边定义中的 `condition` 字段是一个 safe_eval 表达式，在路由函数中被求值：

```python
# 示例边定义
EdgeDefinition(id="e-loop", source="check_done", target="process_next",
               condition="condition_result == True")   # has_more → 继续循环
EdgeDefinition(id="e-exit", source="check_done", target="output",
               condition="condition_result == False")  # 没有更多 → 退出
```

---

### 2.3 safe_eval 沙箱：AST 白名单安全模型

为什么不直接用 Python 的 `eval()`？因为条件表达式来自用户输入（前端 DAG 编辑器），直接 `eval` 等于远程代码执行漏洞。

`safe_eval.py` 实现了一个 **AST 白名单沙箱**：

```python
# safe_eval.py:59-92
def safe_eval(expression: str, context: Dict[str, Any]) -> Any:
    # 1. 长度限制（500 字符）
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise SafeEvalError(...)

    # 2. 解析为 AST（不执行）
    tree = ast.parse(expression, mode="eval")

    # 3. 递归求值每个 AST 节点
    return _eval_node(tree.body, context)
```

`_eval_node()`（L95-196）是一个递归的 AST 解释器，只处理白名单中的节点类型：

| AST 节点类型 | 对应 Python 语法 | 示例 |
|-------------|----------------|------|
| `ast.Constant` | 字面量 | `42`, `"hello"`, `True` |
| `ast.Name` | 变量引用 | `status`, `count` |
| `ast.Compare` | 比较 | `x > 10`, `status == "success"` |
| `ast.BoolOp` | 布尔逻辑 | `x > 0 and y < 100` |
| `ast.UnaryOp` | 一元运算 | `not is_error`, `-n` |
| `ast.BinOp` | 二元运算 | `x + 1`, `count * 2` |
| `ast.Subscript` | 下标访问 | `data["key"]`, `items[0]` |
| `ast.Attribute` | 属性访问（仅 dict） | `result.status` |
| `ast.List/Tuple/Dict` | 容器字面量 | `[1, 2, 3]` |
| `ast.IfExp` | 三元表达式 | `x if cond else y` |

安全比较运算符白名单（L28-39）：

```python
_SAFE_COMPARE_OPS = {
    ast.Eq: operator.eq,        # ==
    ast.NotEq: operator.ne,     # !=
    ast.Lt: operator.lt,        # <
    ast.LtE: operator.le,       # <=
    ast.Gt: operator.gt,        # >
    ast.GtE: operator.ge,       # >=
    ast.Is: operator.is_,       # is
    ast.IsNot: operator.is_not, # is not
    ast.In: lambda a, b: a in b,     # in
    ast.NotIn: lambda a, b: a not in b,  # not in
}
```

---

### 2.4 路由函数的闭包构造

`_add_conditional_edges()`（L715-801）为每个有条件边的源节点构造一个路由函数：

```python
# graph_builder.py:758-798
def make_router(src_id, cond_edges, default):
    def router(state: Dict[str, Any]) -> str:
        # 获取源节点的输出
        node_output = state.get(src_id, {})

        # 构建求值上下文（state + 源节点输出的快捷引用）
        context = {**state}
        if isinstance(node_output, dict):
            context["result"] = node_output
            if "condition_result" in node_output:
                context["condition_result"] = node_output["condition_result"]

        # 逐条尝试条件边
        for edge in cond_edges:
            result = safe_eval(edge.condition, context)
            if result:
                return edge.target  # 返回目标节点 ID

        return "__default__"  # 没有匹配 → 走默认路径
    return router
```

注意三个设计细节：

1. **上下文注入**：路由函数把源节点输出中的 `condition_result` 提升为顶层变量，让表达式可以直接写 `condition_result == True` 而不是 `check_done["condition_result"] == True`

2. **有序求值**：条件边按顺序尝试，第一个匹配的生效（类似 if-elif）

3. **默认路由**：`path_map["__default__"]` 对应无条件边或 `END`，保证即使所有条件都不满足也有出路

---

### 2.5 安全边界：什么能写，什么不能写

**允许的表达式**：

```python
# 比较
"status == 'success'"
"count > 0"
"has_more == True"

# 布尔组合
"status == 'success' and retry_count < 3"
"is_error or timeout"

# 字段访问
"result['status'] == 'ok'"
"condition_result == True"

# 算术
"current_index + 1 < total"

# 三元
"'retry' if retry_count < 3 else 'abort'"

# in 运算
"status in ['success', 'partial']"
```

**禁止的表达式**（`validate_condition_expression()` L199-241 会拒绝）：

```python
# ❌ 函数调用
"len(items) > 0"           # ast.Call 被阻止
"print('hacked')"          # ast.Call 被阻止

# ❌ Lambda
"lambda x: x > 0"          # ast.Lambda 被阻止

# ❌ 列表推导
"[x for x in items]"       # ast.ListComp 被阻止

# ❌ await
"await some_coroutine()"   # ast.Await 被阻止

# ❌ import
"__import__('os')"         # ast.Call 被阻止
```

> **安全设计原则**：safe_eval 采用的是"白名单 + 递归解释"模式，而非"黑名单 + 限制"模式。任何未在 `_eval_node()` 中显式处理的 AST 节点类型都会触发 `SafeEvalError`，这比试图封堵所有危险构造要安全得多。

---

## S3: 循环检测与运行时控制

### 3.1 为什么需要循环

典型场景：**批量 Bug 修复**需要遍历一组 Bug URL，每次处理一个：

```
[初始化] → [取当前 Bug] → [LLM 修复] → [验证] → [更新索引] → [检查是否还有] ─┐
                ↑                                                              │
                └──── 还有更多 Bug ──────────────────────────────────────────────┘
                                     没有了 → [输出结果] → END
```

这个循环图有一个"回边"（从 `检查是否还有` 回到 `取当前 Bug`），在 DAG 中是不允许的，但在工作流中很常见。

项目的设计是：**允许循环，但必须有条件出口**。

---

### 3.2 DFS 环检测：detect_loops()

`detect_loops()`（L403-485）使用**深度优先搜索**找到所有环：

```python
# graph_builder.py:403-485（简化版）
def detect_loops(workflow: WorkflowDefinition) -> List[LoopInfo]:
    graph = defaultdict(list)  # 邻接表
    for edge in workflow.edges:
        if edge.target != END:
            graph[edge.source].append(edge.target)

    loops = []
    visited = set()
    path = []         # 当前 DFS 路径
    path_set = set()  # 快速查找
    found_cycles = set()  # 去重

    def dfs(node):
        if node in path_set:  # 回到路径上的节点 → 发现环！
            cycle_start_idx = path.index(node)
            cycle_path = path[cycle_start_idx:] + [node]
            # ... 检查是否为受控循环
            loops.append(LoopInfo(...))
            return

        if node in visited:
            return

        visited.add(node)
        path.append(node)
        path_set.add(node)

        for neighbor in graph[node]:
            dfs(neighbor)

        path.pop()
        path_set.remove(node)

    for node in workflow.nodes:
        if node.id not in visited:
            dfs(node.id)

    return loops
```

算法要点：

1. **`path` vs `visited`**：`visited` 记录"已经完全探索过的节点"，`path` 记录"当前 DFS 路径上的节点"。如果遇到 `path` 中已有的节点，就发现了环；如果遇到 `visited` 中的节点，说明已经探索过，无需重复。

2. **环去重**：用 `found_cycles` 存储环的节点集合（排序后），避免同一个环被报告多次。

3. **时间复杂度**：O(V + E)，与标准 DFS 相同。

---

### 3.3 受控循环 vs 无出口环路

发现环后，`detect_loops` 会检查环内是否有 `condition` 类型的节点指向环外：

```python
# graph_builder.py:444-460（环内条件出口检测）
for nid in cycle_path[:-1]:
    if node_types.get(nid) == "condition":
        cycle_node_set = set(cycle_path[:-1])
        for neighbor in graph[nid]:
            if neighbor not in cycle_node_set or neighbor == END:
                has_exit = True    # 这个 condition 节点有通往环外的边
                exit_node = nid
                break
```

两种结果：

| 类型 | LoopInfo 字段 | 验证结果 | 含义 |
|------|-------------|---------|------|
| **受控循环** | `has_condition_exit=True` | warning（允许构建） | 有 condition 节点控制退出 |
| **无出口环路** | `has_condition_exit=False` | error（拒绝构建） | 死循环，没有退出条件 |

示例对比：

```
# ✅ 受控循环（check_done 是 condition 节点，有边指向 output）
process → check_done → process（循环）
                     → output（退出）

# ❌ 无出口环路（没有 condition 节点可以退出）
A → B → C → A（死循环）
```

> **拓扑排序兼容**：`topological_sort()`（L544-595）使用 Kahn 算法。对于有受控循环的图，正常的拓扑排序会遗漏循环中的节点（它们的入度永远不为 0）。解决方案是：先排序非循环节点，再按发现顺序追加循环节点。

---

### 3.4 运行时迭代控制：MaxIterationsExceeded

编译时验证只能检查结构，运行时还需要防止无限循环。`executor.py` 实现了**双层保护**：

**第一层：per-node 计数器**（executor.py:100-128）

```python
node_exec_count: Dict[str, int] = defaultdict(int)

async for event in compiled_graph.astream(state, config=config):
    for node_id, node_output in event.items():
        node_exec_count[node_id] += 1

        # 仅对循环节点检查
        if node_id in loop_node_ids and node_exec_count[node_id] > max_iterations:
            raise MaxIterationsExceeded(node_id, current_count, max_iterations)
```

**第二层：LangGraph recursion_limit**（executor.py:114-115）

```python
recursion_limit = max_iterations * len(nodes) + len(nodes)
config = {"recursion_limit": recursion_limit} if has_loops else {}
```

为什么需要两层？
- `recursion_limit` 是 LangGraph 内部的全局步骤上限，防止图执行无限步
- `MaxIterationsExceeded` 是业务层的精确控制，按节点粒度检查

---

### 3.5 递归限制的计算公式

```
recursion_limit = max_iterations × node_count + node_count
```

- `max_iterations × node_count`：循环部分，每次迭代可能执行所有节点
- `+ node_count`：循环外的节点（初始化、输出等）也需要执行一次

例如：5 个节点、最大 10 次迭代 → `recursion_limit = 10 × 5 + 5 = 55`

---

### 3.6 真实案例：批量 Bug 修复的循环工作流

```
get_current_item → llm_agent → verify → update_state → condition → get_current_item（循环）
                                                                 → output（退出）
```

各节点的状态交互：

| 节点 | 读取的状态 | 写入的状态 |
|------|----------|----------|
| `get_current_item` | `bugs[]`, `current_index` | `current_bug`, `has_more` |
| `llm_agent` | `current_bug` | `fix_result` |
| `verify` | `fix_result` | `verify_result` |
| `update_state` | `current_index` | `current_index + 1`, `results[]` |
| `condition` | `has_more` | `condition_result` |

`condition` 节点的配置：
```json
{
  "condition": "has_more == True"
}
```

条件边：
```json
[
  {"source": "condition", "target": "get_current_item", "condition": "condition_result == True"},
  {"source": "condition", "target": "output", "condition": "condition_result == False"}
]
```

**MaxIterationsExceeded 的优雅降级**（executor.py:172-185）：

```python
except MaxIterationsExceeded as e:
    # 不是硬错误！返回已处理的部分结果
    state["loop_terminated"] = True
    state["loop_terminated_node"] = e.node_id
    state["loop_iterations"] = dict(node_exec_count)
    # 继续执行到 workflow_complete
```

> **设计决策**：`MaxIterationsExceeded` 不算失败。如果用户传入 20 个 Bug 但 `max_iterations=10`，前 10 个的处理结果仍然会返回。这比硬错误+全部丢弃要实用得多。

---

## S4: 节点注册表 + 动手练习

### 4.1 策略模式：NODE_REGISTRY + NODE_CLASSES

节点注册表采用经典的**策略模式** — 两个全局 dict 分别存储元数据和实现类：

```python
# registry.py:163-165
NODE_REGISTRY: Dict[str, NodeDefinition] = {}   # node_type → 元数据
NODE_CLASSES: Dict[str, Type[BaseNode]] = {}     # node_type → 实现类
```

`NodeDefinition`（L32-65）存储了节点的元数据：

```python
@dataclass
class NodeDefinition:
    node_type: str          # 唯一标识，如 "condition"
    display_name: str       # UI 显示名
    description: str        # 功能描述
    category: str           # 分类，如 "control", "data", "processing"
    input_schema: Dict      # 输入 JSON Schema
    output_schema: Dict     # 输出 JSON Schema
    icon: Optional[str]     # UI 图标
    color: Optional[str]    # UI 主题色
```

这个双 dict 设计的好处：
- `NODE_REGISTRY` 可以独立于实现类导出给前端，用于 DAG 编辑器的节点面板
- `NODE_CLASSES` 只在后端运行时使用
- 两者通过 `node_type` 字符串关联

---

### 4.2 @register_node_type 装饰器

```python
# registry.py:168-231
def register_node_type(
    node_type, display_name, description, category,
    input_schema, output_schema, icon=None, color=None,
) -> Callable[[Type[T]], Type[T]]:
    def decorator(cls: Type[T]) -> Type[T]:
        definition = NodeDefinition(...)
        NODE_REGISTRY[node_type] = definition
        NODE_CLASSES[node_type] = cls
        return cls
    return decorator
```

使用方式：

```python
@register_node_type(
    node_type="condition",
    display_name="Condition",
    description="Routes workflow based on conditional logic",
    category="control",
    input_schema={...},
    output_schema={...},
    icon="git-branch",
    color="#9C27B0",
)
class ConditionNode(BaseNodeImpl):
    async def execute(self, inputs):
        ...
```

> **Python 装饰器原理**：`@register_node_type(...)` 实际上是两步调用。先调用 `register_node_type(...)` 返回 `decorator` 函数，再调用 `decorator(ConditionNode)` 注册类并返回。这是带参数的装饰器的标准写法。

---

### 4.3 BaseNodeImpl 抽象基类

```python
# registry.py:111-160
class BaseNodeImpl(ABC):
    def __init__(self, node_id: str, node_type: str, config: Dict[str, Any]):
        self.node_id = node_id
        self.node_type = node_type
        self.config = config

    @abstractmethod
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def validate_config(self) -> List[Dict[str, str]]:
        # 默认实现：检查 input_schema 中的 required 字段
        definition = NODE_REGISTRY.get(self.node_type)
        required_fields = definition.input_schema.get("required", [])
        for field_name in required_fields:
            if field_name not in self.config:
                errors.append(...)
        return errors
```

注意 `BaseNode`（L68-108）是 `Protocol`（接口），`BaseNodeImpl`（L111-160）是 ABC（抽象类）。项目中所有节点都继承 `BaseNodeImpl`，但类型系统通过 `Protocol` 实现鸭子类型兼容。

工厂函数 `create_node()`（L234-272）：

```python
def create_node(node_id, node_type, config) -> BaseNode:
    if node_type not in NODE_CLASSES:
        raise ValueError(f"Unknown node type: {node_type}. Available: {list(NODE_CLASSES.keys())}")
    node_class = NODE_CLASSES[node_type]
    return node_class(node_id=node_id, node_type=node_type, config=config)
```

---

### 4.4 现有节点类型一览

| 节点类型 | 类名 | 文件 | 分类 | 用途 |
|---------|------|------|------|------|
| `data_source` | DataSourceNode | base.py | data | 提供初始数据 |
| `data_processor` | DataProcessorNode | base.py | processing | 数据转换 |
| `http_request` | HttpRequestNode | base.py | integration | HTTP 请求 |
| `condition` | ConditionNode | base.py | control | 条件分支 |
| `output` | OutputNode | base.py | output | 输出结果 |
| `get_current_item` | GetCurrentItemNode | state.py | state | 数组迭代取值 |
| `update_state` | UpdateStateNode | state.py | state | 状态更新 |
| `llm_agent` | LLMAgentNode | agents.py | agent | Claude CLI 调用 |
| `verify` | VerifyNode | agents.py | validation | 修复结果验证 |
| `design_analyzer` | DesignAnalyzerNode | design.py | analysis | 设计文件分析 |
| `frame_decomposer` | FrameDecomposerNode | frame_decomposer.py | analysis | 结构提取 |
| `spec_analyzer` | SpecAnalyzerNode | spec_analyzer.py | analysis | LLM 视觉分析 |
| `spec_assembler` | SpecAssemblerNode | spec_assembler.py | output | 规格组装 |

> **扩展模式**：添加新节点只需要：(1) 创建一个继承 `BaseNodeImpl` 的类，(2) 用 `@register_node_type` 装饰器注册。不需要修改引擎代码。这就是策略模式的优势。

---

### 4.5 动手练习：构造 3 节点循环工作流

**目标**：构造一个「计数器」工作流，从 0 数到 3 然后停止。

**工作流结构**：

```
data_source → condition → update_state ─┐
                  │                      │
                  └───── count < 3 ──────┘
                  │
                  └───── count >= 3 → output → END
```

**练习代码**：

```python
from workflow.engine.graph_builder import (
    WorkflowDefinition, NodeConfig, EdgeDefinition,
    build_graph_from_config, validate_workflow,
)
from langgraph.graph import END

# 1. 定义工作流
workflow = WorkflowDefinition(
    name="counter_demo",
    nodes=[
        NodeConfig(id="init", type="data_source", config={
            "name": "Initialize Counter",
            "source_type": "manual",
        }),
        NodeConfig(id="check", type="condition", config={
            "name": "Check Counter",
            "condition": "count < 3",  # safe_eval 表达式
        }),
        NodeConfig(id="increment", type="update_state", config={
            "name": "Increment Counter",
            "updates": [
                {"field": "count", "expression": "count + 1"},
            ],
        }),
        NodeConfig(id="done", type="output", config={
            "name": "Output Result",
            "format": "json",
        }),
    ],
    edges=[
        EdgeDefinition(id="e1", source="init", target="check"),
        EdgeDefinition(id="e2", source="check", target="increment",
                       condition="condition_result == True"),
        EdgeDefinition(id="e3", source="check", target="done",
                       condition="condition_result == False"),
        EdgeDefinition(id="e4", source="increment", target="check"),
        EdgeDefinition(id="e5", source="done", target=END),
    ],
    max_iterations=5,  # 安全上限
)

# 2. 验证
result = validate_workflow(workflow)
print(f"Valid: {result.valid}")
for w in result.warnings:
    print(f"  Warning: {w.message}")
# 预期输出：
# Valid: True
# Warning: 检测到受控循环：check → increment → check（由 condition 节点 'check' 控制退出）

# 3. 构建并执行
import asyncio
from workflow.engine.executor import execute_dynamic_workflow

async def run():
    state = await execute_dynamic_workflow(
        workflow_def=workflow,
        initial_state={"count": 0},
        run_id="demo-001",
    )
    print(f"Final count: {state.get('count')}")
    print(f"Iterations: {state.get('node_execution_counts')}")

asyncio.run(run())
# 预期输出：
# Final count: 3
# Iterations: {'init': 1, 'check': 4, 'increment': 3, 'done': 1}
```

**思考题**：

1. 为什么 `check` 节点执行了 4 次？（提示：count=0,1,2 时进入循环，count=3 时退出）
2. 如果把 `max_iterations` 改为 2，会发生什么？（提示：`MaxIterationsExceeded` 不是硬错误）
3. 如果去掉 `check` 节点的 condition 类型，改为 `data_processor`，验证会报什么错？
4. 如何修改工作流让它倒数（从 3 到 0）？

---

## 关键文件索引

| 文件 | 行数 | 核心内容 |
|------|------|---------|
| `workflow/engine/graph_builder.py` | 813 | 声明式定义 + 验证 + 编译 + 条件路由 |
| `workflow/engine/executor.py` | 212 | astream 执行器 + SSE 推送 + 循环控制 |
| `workflow/engine/safe_eval.py` | 241 | AST 沙箱表达式求值 |
| `workflow/nodes/registry.py` | 321 | 策略模式节点注册表 |
| `workflow/nodes/base.py` | 374 | 5 个基础节点实现 |
| `workflow/nodes/state.py` | 435 | 循环工作流的状态管理节点 |

---

## 踩坑集锦

### 坑 1：LangGraph 内部/外部状态脱节

**现象**：循环工作流中，executor 维护的外部 `state` 字典和 LangGraph `astream` 内部维护的状态不同步。导致 `component_registry` 等累积字段在外部始终为空。

**根因**：`astream` 流式输出的 `event` 是 `{node_id: node_output}`，其中 `node_output` 是 LangGraph 内部完整状态的快照。早期代码只做了 `state[node_id] = node_output`，没有合并 `node_output` 中的其他字段。

**修复**（executor.py:151-154）：

```python
# 修复后：完整合并 astream 输出到外部 state
if isinstance(node_output, dict):
    state.update(node_output)  # 合并所有字段
else:
    state[node_id] = node_output
```

### 坑 2：state merge 白名单 → 黑名单

**现象**：Design-to-Spec 管线的 `components`、`design_tokens` 字段在状态合并后消失。

**根因**：引擎层使用白名单只允许 Batch Bug Fix 的字段（`bugs`, `current_index`）通过，Design 管线的字段被静默过滤。

**修复**：改为黑名单（graph_builder.py:91-93），只排除已知内部元数据。详见 S1.4。

### 坑 3：递归限制传参方式变更

**现象**：`StateGraph.compile(recursion_limit=N)` 报 `TypeError`。

**根因**：LangGraph API 变更，`compile()` 不再接受 `recursion_limit`。

**修复**：改为运行时传参：

```python
# ❌ 旧写法
graph.compile(recursion_limit=55)

# ✅ 新写法
compiled_graph.astream(state, config={"recursion_limit": 55})
```

### 坑 4：闭包变量捕获

**现象**：循环中创建的 `node_func` 闭包全部引用最后一个 `node_instance`。

**防御**（graph_builder.py:650）：

```python
def make_node_func(node_instance, _skip=skip_keys):
    # node_instance 通过参数绑定，避免闭包引用循环变量
    ...
```

### 坑 5：falsy 空列表

**现象**：`data.get("components")` 返回 `[]`（空列表），但 `if not data.get("components")` 判断为 True，导致误认为字段不存在。

**修复**：用 `"components" in data` 检查字段存在性，而非依赖 truthy/falsy。
