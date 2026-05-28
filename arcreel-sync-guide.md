# ArcReel 更新采纳式同步指南

本文用于约束 AI 在维护 `manju` 小蜗插件时，如何参考 `E:\rust_python\ArcReel` 仓库的更新，并选择性同步到 `D:\rust_app\xiaowo\plugins\manju`。

核心原则：**manju 不是 ArcReel 的机械镜像，而是 ArcReel 的小蜗桌面插件变体。同步时必须先判断是否适合 manju，再按 manju 的结构和桌面插件需求改造。**

## 本次对齐记录

- 本次同步来源：`E:\rust_python\ArcReel`
- 本次 pull 记录：`2026-05-26 15:44:52 +0800`，`merge origin/main: Fast-forward`
- 本次检查范围：`9cada0c..c27c30c`
- 本次已对齐到 ArcReel commit：`c27c30c3568558d1ce3d238feb39d1c72bd69adb`（短 hash：`c27c30c`）
- 后续继续同步时，默认以 `c27c30c3568558d1ce3d238feb39d1c72bd69adb` 作为已对齐基线，只评估 ArcReel 在此之后新增的更新。

## 本地审查待处理问题

记录时间：`2026-05-26`

| 编号 | 问题 | 风险 | 当前状态 |
| --- | --- | --- | --- |
| `MANJU-REVIEW-001` | `GenerationWorker` 取消 running 任务时，`_process_task` / `_process_resume_task` 捕获 `asyncio.CancelledError` 后重新抛出；但 `_drain_finished_tasks()` 只捕获 `Exception`，在 Python 3.13 中 `CancelledError` 继承 `BaseException`，可能导致一个任务取消把 worker 主循环带停。 | 高：取消单个任务可能让后续队列不再执行。 | manju 已先行修复：`_drain_finished_tasks()` 显式处理已落地的 `asyncio.CancelledError`，并补充回归测试。ArcReel `c27c30c` 同样存在此问题，但本次不修改 ArcReel。 |
| `MANJU-REVIEW-002` | 图片任务入队和 worker 限流路由固定按 `capability="t2i"` 解析 provider；实际执行层遇到参考图会走 I2I。若项目的 T2I / I2I provider 不同，限流池可能按错误 provider 统计。 | 中：可能压错并发池、绕过真实 I2I provider 限流或错误阻塞 T2I。 | manju 已先行修复：队列入库和 worker 分发共用图片任务 capability 预判，按实际 T2I / I2I provider 路由并补充回归测试。ArcReel `c27c30c` 同样存在此问题，但本次不修改 ArcReel。 |

本地先行修复验证：`2026-05-26` 使用插件 manifest 中 dev 后端 Python `D:\ProgramData\miniconda3\envs\manju\python.exe` 运行 `tests\test_generation_worker_module.py`、`tests\test_generation_queue.py`、`tests\test_generation_tasks_service.py`、`tests\test_grid_executor.py`，结果 `107 passed`。

## Claude Agent SDK 官网对照记录

记录时间：`2026-05-28`

本节不是 ArcReel 同步项，而是 manju agent runtime 与 Claude Agent SDK 官方方案的差异账本。后续升级 `claude-agent-sdk`、Claude Code CLI 或对照官网文档时，应先看这里：如果官网提供了更稳、更窄、更可维护的方案，则采纳官网方案；如果官网仍只是通用权限能力，继续保留 manju 的桌面插件约束。

参考官网页面：

- `https://code.claude.com/docs/en/agent-sdk/permissions`
- `https://code.claude.com/docs/en/agent-sdk/user-input`
- `https://platform.claude.com/docs/en/agent-sdk/python`

| 项目 | 官网方案 / 事实 | manju 当前做法 | 当前判断 | 后续对照重点 |
| --- | --- | --- | --- | --- |
| 权限链顺序 | 工具调用按 Hooks → deny rules → permission mode → allow rules → `canUseTool` callback 处理；未被 `allowed_tools` 预批准的工具仍可落到 `canUseTool`。 | Windows sandbox 不可用时，不把 shell 类工具作为泛用自动批准入口；`Bash` / `PowerShell` 落到 `_build_can_use_tool_callback()` 的白名单。 | 采纳官网权限链，但保留 manju 的运行时白名单。 | 若官网新增更细的 shell scoped allow / deny API，可评估替换自维护解析器。 |
| `allowed_tools` 语义 | `allowed_tools` 是自动批准列表，不是工具能力边界；真正要硬限制需配合 `dontAsk` 或 deny。 | `PowerShell` 不加入 `DEFAULT_ALLOWED_TOOLS`；避免 Windows 正式环境中把任意 PowerShell 自动批准。 | 保持。 | 若将来有人把 `PowerShell` 写入 settings allow，应重新审查，避免绕过 env scrub 与白名单。 |
| `canUseTool` 返回值 | `PermissionResultAllow(updated_input=...)` 可允许并修改工具输入；`PermissionResultDeny(message=...)` 可拒绝并把原因反馈给 agent。 | 对白名单通过的 `PowerShell` 命令，用 `updated_input` 包装命令：先清理敏感环境变量，再执行原命令。 | 采纳官网能力，作为当前最贴合的修复。 | 若官网提供官方 shell env scrub / sandbox wrapper，优先评估替换本地 wrapper。 |
| Python SDK hooks | Python `can_use_tool` 场景需要保留 `PreToolUse` keep-alive hook；hooks 可在 `canUseTool` 前运行并阻断请求。 | manju 已保留 `_keep_stream_open_hook`；文件访问、JSON 校验等继续走 hooks；PowerShell env scrub 放在 `canUseTool` 的 `updated_input`，避免泛用 hook 自动放大权限面。 | 保持。 | 每次 SDK 升级确认 keep-alive hook 是否仍必要、hook 返回结构是否变化。 |
| 自定义业务能力 | 官网支持 `create_sdk_mcp_server()` 创建进程内 MCP，并通过 `mcp__server__tool` 放入 `allowed_tools`。 | manju 业务优先走 `mcp__arcreel__*` 进程内工具；只有 `.claude/skills/*.py`、`ffmpeg`、`ffprobe` 这类受控本地命令才走 shell 白名单。 | 保持。 | 若官网 MCP 工具 schema / annotations 有更好安全标注，可优先补到 `arcreel` MCP 工具层。 |

当前结论：

- 不采用“把 `PowerShell` 加入 `allowed_tools`”的简单方案，因为这会把自动批准面放大到任意 PowerShell 调用。
- 不采用纯交互审批方案，因为小蜗 Tauri 正式环境中 agent 子进程不应依赖终端式人工 y/n。
- 采用官网推荐的 `canUseTool + updated_input` 能力，但在 manju 内部叠加桌面插件自己的命令白名单、env scrub、跨项目读写限制。

## 项目差异

| 项目 | 定位 | 前后端通信 | 运行方式 | 同步时的判断重点 |
| --- | --- | --- | --- | --- |
| `ArcReel` | WebUI 项目 | 前端通过 FastAPI HTTP 接口调用 Python 后端 | 前端服务和后端 Python 服务分别启动 | 功能逻辑、算法、提示词、资源处理、Bug 修复是否有价值 |
| `manju` | 小蜗桌面软件插件 | 通过小蜗插件 SDK / 进程间通信调用插件后端 | 由小蜗宿主加载插件窗口和插件后端 | 是否符合桌面插件体验、SDK 生命周期、现有 UI/UX 和本地文件能力 |

不要把 ArcReel 的 FastAPI 路由、Web 启动方式、Web 部署配置直接搬进 manju。需要把可采纳的功能转换为 manju 当前的前端组件、插件 SDK 调用、Python 后端 handler、事件流和本地文件流程。

## 输入要求

每次执行同步检查时，用户应尽量提供以下信息：

- ArcReel 的更新时间范围：例如 `2026-05-01..2026-05-26`，或起止 commit。
- 如果用户说“刚刚拉取了 ArcReel 更新”，默认检查的是**本次 pull 实际带来的 commit 范围**，不是 Git 上“今天提交”的 commit。优先用 `ORIG_HEAD..HEAD`，若不可靠则用 `git reflog` 找到最新 pull / merge / rebase 的前后 commit。
- 是否只分析，还是允许直接修改 manju。
- 是否需要提交 / 推送。未明确要求时，不要执行 git commit / git push。

如果用户只说“检查 ArcReel 最近更新是否要同步”，AI 应先产出同步评估报告，不要直接大改。

如果用户明确说“全部更新”“包括需要我决定的也更新”等同类指令，则视为已授权把“需要用户决定”的项一并采纳；但仍必须按 manju 桌面插件架构改造，且不得同步与插件运行无关的 Web 部署、CI、仓库治理或外部 agent 配置。

## 推荐检查命令

在 ArcReel 仓库查看指定时间段更新：

```powershell
rtk git -C E:\rust_python\ArcReel log --since="2026-05-01" --until="2026-05-26 23:59:59" --oneline --decorate
rtk git -C E:\rust_python\ArcReel log --since="2026-05-01" --until="2026-05-26 23:59:59" --name-status --pretty=format:"%h %ad %s" --date=short
rtk git -C E:\rust_python\ArcReel show --stat <commit>
rtk git -C E:\rust_python\ArcReel show --name-only <commit>
```

如果用户刚执行过 pull，优先查看本次 pull 带来的更新：

```powershell
rtk git -C E:\rust_python\ArcReel reflog --date=iso -n 10
rtk git -C E:\rust_python\ArcReel rev-parse ORIG_HEAD
rtk git -C E:\rust_python\ArcReel rev-parse HEAD
rtk git -C E:\rust_python\ArcReel log --oneline --decorate ORIG_HEAD..HEAD
rtk git -C E:\rust_python\ArcReel diff --name-status ORIG_HEAD..HEAD
```

如果 `ORIG_HEAD` 不存在，或不是本次 pull 前的 commit，则从 `reflog` 找最新的 `pull` / `merge` / `rebase` 记录，用 `HEAD@{1}..HEAD` 或对应 reflog 前后 commit 作为范围。不要用 `--since=今天` 代替本次拉取范围，因为今天拉取的内容可能是多天前已经提交的 commit。

在 manju 仓库确认当前状态：

```powershell
rtk git -C D:\rust_app\xiaowo\plugins\manju status --short
rtk git -C D:\rust_app\xiaowo\plugins\manju branch --show-current
```

必要时对比同名或同职责文件，但不要假设路径完全一致。

## 同步决策分类

AI 必须把 ArcReel 更新分成以下四类：

### 1. 建议同步

满足以下条件之一：

- 修复核心生成流程、项目数据、资源读写、任务状态、成本统计、重试恢复等真实问题。
- 改进提示词、模型参数、生成策略、分镜 / 宫格 / 角色 / 场景 / 道具等核心业务能力。
- 修复安全、数据丢失、路径处理、并发任务、异常恢复、文件覆盖等高风险问题。
- 改进用户体验，且不破坏 manju 已有桌面插件交互。
- 增加通用测试、类型修正、边界处理，能降低 manju 维护风险。

### 2. 需要改造后同步

ArcReel 的思路有价值，但实现不能直接搬：

- FastAPI router / HTTP API 变更，需要转成 manju 后端 handler 或现有 `API` / `useBackend` 调用方式。
- Web 文件上传 / 下载 / URL 预览，需要转成小蜗桌面文件选择、保存对话框、本地路径和 `PluginSDK.convertFileSrc`。
- Web 页面布局可参考，但必须落到 manju 当前组件体系、主题变量、i18n 和桌面窗口尺寸。
- ArcReel 新增长任务轮询，需要映射到 manju 的任务事件、后端事件订阅、任务 HUD 或现有 store。
- ArcReel 的配置项有价值，但 manju 应接入插件设置、全局设置或小蜗宿主上下文。

### 3. 不建议同步

通常不应同步：

- WebUI 启动脚本、FastAPI 服务启动方式、Docker / Web 部署 / 反向代理相关变更。
- 只服务浏览器环境的交互、鉴权、跨域、Web 路由、URL 参数逻辑。
- 与 manju 已有桌面体验冲突的 UI 重排，尤其是会破坏插件窗口、标题栏、文件对话框、任务状态展示的改动。
- 已被 manju 自己优化过、且 ArcReel 更新只是较弱或不适配的同类实现。
- 临时调试、示例数据、纯项目私有脚本、无关文档。

### 4. 需要用户决定

AI 无法明确判断时，必须列为“需要用户决定”，不要擅自同步：

- 新功能会改变 manju 当前产品方向、工作流入口、费用策略或生成默认行为。
- ArcReel 与 manju 对同一体验已经走了不同方向。
- 需要新增较大依赖、改动数据结构、迁移已有项目数据。
- 可能增加后端运行成本、模型调用成本或显著影响生成速度。
- 需要放弃 manju 已有优化来跟随 ArcReel。

## 映射规则

| ArcReel 更新位置 / 类型 | manju 中的处理方向 |
| --- | --- |
| 前端页面 / React 组件 | 先找 `frontend/src/components/*` 和现有 UI 原语；保持 manju 的桌面插件视觉语言 |
| FastAPI route / HTTP endpoint | 不直接复制 route；转成插件后端 handler 或复用现有后端调用封装 |
| 前端 HTTP client | 映射到 manju 当前 `API`、`useBackend`、`PluginSDK.callBackend` 或已有 store |
| 文件上传 / 下载 | 使用小蜗文件/目录/保存对话框能力，不使用 Web 下载假设 |
| 本地路径 / 资源 URL | 检查 manju 的资源根、文件指纹、`convertFileSrc` 和缓存刷新逻辑 |
| 任务轮询 / SSE / WebSocket | 优先映射为插件后端事件、任务 HUD、store revision 或现有轮询封装 |
| i18n 文案 | 使用 manju 插件自己的 i18n 结构；语言跟随主程序，不新增手动切换 |
| UI 主题 | 使用 manju 当前 `components/ui/*` 和样式变量，不套 ArcReel WebUI 皮肤 |
| 测试 | 按 manju 当前 Vitest / TypeScript / ESLint 流程补充 |

## AI 执行流程

### 第一步：读取上下文

1. 确认 ArcReel 更新时间范围或 commit 范围。
2. 查看 ArcReel 更新列表和关键 diff。
3. 查看 manju 当前对应模块实现。
4. 确认 manju 工作区状态，避免混入无关改动。

### 第二步：产出同步评估

必须先输出表格：

| ArcReel 更新 | 类型 | 对 manju 的价值 | 分类 | 建议动作 | 需要用户确认 |
| --- | --- | --- | --- | --- | --- |
| commit / 文件 / 功能摘要 | Bug / 功能 / UI / 后端 / 配置 | 高 / 中 / 低 | 建议同步 / 改造后同步 / 不同步 / 用户决定 | 简述如何处理 | 是 / 否 |

评估时要说明：

- ArcReel 改了什么。
- manju 当前是否已有类似能力。
- 直接同步会不会破坏桌面插件结构。
- 如果采纳，应该落在哪些 manju 文件或模块。

### 第三步：等待或执行

- 如果用户要求“只检查 / 审查 / 评估”，到评估报告为止，不修改代码。
- 如果用户要求“帮我同步 / 开始修改”，只实现分类为“建议同步”和用户已确认的项。
- 分类为“需要用户决定”的项，必须先问用户，不要自行假设。

### 第四步：实现规则

实现时必须遵守：

- 保留 manju 当前桌面插件结构，不把 ArcReel 的 Web 服务结构搬进来。
- 优先复用 manju 已有组件、store、API、后端 handler、工具函数和 i18n。
- 不覆盖 manju 已有体验优化，除非用户明确要求。
- 同一问题 manju 已有更适配桌面的实现时，以 manju 为准。
- 每次改动应尽量小范围、可验证、可回滚。
- 涉及前后端协议时，必须同时检查调用方和被调用方。
- 涉及资源文件、路径、下载、导入导出时，必须按桌面软件能力验证。

### 第五步：验证

根据改动范围选择验证：

```powershell
cd D:\rust_app\xiaowo\plugins\manju\frontend
rtk pnpm typecheck
rtk pnpm lint
rtk pnpm test
```

涉及后端时，还应运行对应后端测试或最小可行检查。若没有可运行测试，要在结果中明确说明未验证的风险。

### 第六步：总结

最终总结必须包含：

- 本次参考了 ArcReel 哪个时间段 / 哪些 commit。
- 哪些更新已采纳。
- 哪些更新未采纳，以及原因。
- 哪些需要用户后续决定。
- manju 中实际改了哪些模块。
- 执行过哪些验证。

## 固定输出模板

```markdown
## ArcReel 更新采纳评估

范围：
- ArcReel：<时间范围或 commit 范围>
- manju：<当前分支 / 当前 commit>

### 建议同步
| 更新 | 原因 | manju 落点 | 风险 |
| --- | --- | --- | --- |

### 改造后同步
| 更新 | ArcReel 实现 | manju 改造方式 | 风险 |
| --- | --- | --- | --- |

### 不建议同步
| 更新 | 不同步原因 |
| --- | --- |

### 需要用户决定
| 更新 | 需要决定的问题 | 可选方向 |
| --- | --- | --- |

## 执行结果

- 已采纳：
- 已跳过：
- 待确认：
- 验证：
```

## 可直接给 AI 的提示词

```text
请根据 D:\rust_app\xiaowo\plugins\manju\arcreel-sync-guide.md，检查 E:\rust_python\ArcReel 在 <时间范围或 commit 范围> 的更新。

先产出采纳评估报告，不要直接修改代码。
重点判断：
1. 哪些更新适合同步到 manju。
2. 哪些需要按小蜗桌面插件结构改造后同步。
3. 哪些不需要同步。
4. 哪些需要我决定。

注意：manju 是小蜗桌面插件，通信方式和 ArcReel WebUI 不同，不能机械复制 FastAPI / WebUI 实现。
```

如果用户已经明确要求执行同步，可改为：

```text
请根据 D:\rust_app\xiaowo\plugins\manju\arcreel-sync-guide.md，检查并同步 E:\rust_python\ArcReel 在 <时间范围或 commit 范围> 中适合 manju 的更新。

只同步“建议同步”和我已确认的“改造后同步”内容。
不要同步 WebUI 启动、FastAPI 路由、部署配置等不适合桌面插件的内容。
完成后运行必要验证，并总结采纳、跳过和待确认项。
```
