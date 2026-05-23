# ArcReel 插件前后端执行语义审查记录

本文档记录 `plugins/manju` 将 ArcReel WebUI 封装为小蜗桌面插件过程中，按
`ARCREEL_PLUGIN_REVIEW_CONSTRAINTS.md` 做前端功能事件到后端实际执行链路审查后发现的问题。

本文件记录当前审查结论和已落地修复。2026-05-23 本轮修复基于新版
`xiaowo-sdk` 的 FastAPI-like 多请求处理模型：插件后端主循环持续读取 stdin，
async handler 在 SDK 常驻事件循环内运行，同步 handler 在线程池运行。

## 审查目标

- 确认当前插件前端操作触发的后端任务、子任务或进程，是否与原 ArcReel WebUI 通过 HTTP / SSE 触发的业务逻辑一致。
- 判断差异是否只是通信方式从 HTTP / SSE 替换为小蜗 IPC / 事件轮询，还是已经改变了后端真实执行语义。
- 继续遵守小蜗插件后端约束：不使用 `threading.Thread(target=worker); t.start()` 承载后台任务，长任务优先使用子进程、现有队列 worker、异步请求或任务批处理。

## 当前已确认对齐的链路

### 普通业务请求

当前普通 `API.request(...)` 仍保留 ArcReel 原前端 API 方法形态，底层由运行时适配：

`frontend/src/plugin-runtime.ts`

- `fetch(...)` 被拦截。
- `/api/v1/...` 资源被转换为 `operation + resource + query + body`。
- 通过 `PluginSDK.callBackend("arcreel_resource_request", ...)` 进入插件后端。

`backend/handlers.py`

- `arcreel_resource_request` 转到 `utils/arcreel_ipc_bridge.dispatch_desktop_resource_request(...)`。

`backend/utils/arcreel_desktop_routes.py`

- 根据原 FastAPI router 路由表匹配 endpoint。
- 当前覆盖项目、文件、素材、生成、任务、provider、system config、agent config、custom provider、cost、grid、reference video、assets 等原 router。
- 不覆盖登录、API Key、浏览器下载 token、系统日志浏览器下载等不需要在单插件里保留的 Web 服务对外能力。

### 生成任务

项目内生成类功能仍进入原 router 并入队：

- storyboard: `server.routers.generate.generate_storyboard`
- video: `server.routers.generate.generate_video`
- character / scene / prop: `server.routers.generate.generate_character / generate_scene / generate_prop`
- grid: `server.routers.grids.generate_grid / regenerate_grid`
- reference video unit: `server.routers.reference_videos.generate_unit`

这些 endpoint 仍调用原 `GenerationQueue.enqueue_task(...)`，任务执行由 `utils/arcreel_ipc_bridge._ensure_worker_process()` 启动独立 Python 子进程 `utils/arcreel_worker_process.py`，再由原 `lib.generation_worker.GenerationWorker` 消费队列。

该链路符合小蜗约束：没有用 `threading.Thread(...).start()` 承载生成任务。

### 文件上传、导入和资产图片

当前文件型 API 使用 `requestWithLocalFiles(...)`：

- `importProject`
- `uploadFile`
- `uploadStyleImage`
- `createAsset`
- `replaceAssetImage`
- `uploadVertexCredential`

底层通过 `PluginSDK.callBackend("arcreel_local_file_request", ...)` 进入后端，再由 `dispatch_desktop_file_resource(...)` 构造与 FastAPI `UploadFile` 兼容的对象，调用原 router endpoint。

字段名与原接口保持一致：

- 普通上传使用 `file`
- 全局资产图片使用 `image`
- form 字段继续传入原 endpoint 的 `Form(...)` 参数

### 任务状态和取消

任务列表、统计、取消、批量取消仍调用原 tasks router：

- `server.routers.tasks.list_tasks`
- `server.routers.tasks.get_task_stats`
- `server.routers.tasks.cancel_task`
- `server.routers.tasks.cancel_all_queued`

`API.openTaskStream({ lastEventId })` 的旧 SSE 兼容层已经按原 FastAPI 逻辑处理 `last_event_id`，snapshot 中返回 `max(cursor, latest_event_id)`。

当前 UI 主要仍使用 3 秒轮询任务列表和统计；旧 stream API 作为兼容层保留。

### 桌面导出和诊断包

浏览器下载 token 不再保留，改为桌面 IPC 直接返回二进制：

- `arcreel_export_project_archive`
- `arcreel_export_jianying_draft`
- `arcreel_download_diagnostics`

这些入口仍调用原服务层：

- `server.services.project_archive.ProjectArchiveService`
- `server.services.jianying_draft_service.JianyingDraftService`
- `server.services.diagnostics.collect_diagnostics`

这属于 Web 下载形态替换为桌面 IPC，不视为业务缺失。

## 已解决的问题

### P1: Assistant 后台执行模型不再使用 IPC fresh loop

原问题：

- 前端 Assistant 仍通过 `API.sendAssistantMessage(...)` 调用原 assistant router。
- 后端 `arcreel_resource_request` 最终进入 `server.routers.assistant.send_message(...)`。
- 原 ArcReel Assistant 依赖 FastAPI 常驻事件循环。
- 旧 IPC bridge 使用 fresh event loop 执行每次请求：`asyncio.run(...)` 创建事件循环，handler 返回后事件循环结束。

修复：

- `backend/handlers.py` 中 ArcReel 资源、事件、文件和导出入口改为 `async def`。
- `backend/utils/arcreel_ipc_bridge.py` 中 `dispatch_desktop_resource_request(...)`、`build_event_snapshot(...)`、`poll_event_streams(...)` 等公开入口改为 async 入口，直接运行在新版 SDK 常驻 runtime loop。
- 运行链路不再调用 `_run_in_fresh_loop(...)`，也不再每次请求结束后关闭 `httpx` client / DB engine。
- `SessionActor.start()`、`SessionManager.send_new_session(...)`、`send_message(...)` 创建的 actor / inbox / cleanup 等后台 task 会继续留在 SDK 常驻事件循环中。
- 桌面运行时显式执行 `assistant_service.startup()`，并启动 `session_manager.start_patrol()`，补齐原 FastAPI lifespan 中 Assistant 后台巡检任务。

当前语义：

- Assistant 不再需要额外子进程即可获得接近原 FastAPI lifespan 的持久事件循环语义。
- 前端继续通过原 ArcReel API 方法触发 assistant router，事件轮询继续把 `snapshot / patch / delta / question / compact / status` 映射为小蜗插件事件。
- 仍需注意：插件窗口关闭时宿主会结束整个 Python 后端进程，未完成的 Assistant 会话会随进程退出中断；这与桌面插件生命周期一致。

### P2: Provider / Custom Provider 设置变更会刷新已运行的生成 worker 子进程

原问题：

- 原 ArcReel Web 服务中，provider 或 custom provider 设置变更会调用 `_invalidate_caches(request)`。
- `_invalidate_caches(...)` 会执行：
  - `server.services.generation_tasks.invalidate_backend_cache()`
  - `request.app.state.generation_worker.reload_limits()`
- 旧桌面 dispatcher 构造的 fake request 中 `request.app.state.generation_worker` 是 `None`。
- 桌面插件真正的生成 worker 在独立子进程 `utils/arcreel_worker_process.py` 中运行。

修复：

- `backend/utils/arcreel_desktop_routes.py` 为 fake request 挂载 `_DesktopGenerationWorkerProxy`。
- 原 provider / custom provider router 仍按原逻辑调用 `_invalidate_caches(request)`。
- proxy 的 `reload_limits()` 写入桌面 worker reload marker。
- `backend/utils/arcreel_worker_process.py` 在独立 worker 进程内轮询 reload marker；检测到变更后执行：
  - `server.services.generation_tasks.invalidate_backend_cache()`
  - `worker.reload_limits()`
- worker 启动后也会先执行一次 `worker.reload_limits()`，让初始并发池从 DB 配置加载，而不是长期停留在默认 env 池配置。

当前语义：

- 主进程和 worker 子进程都会清理自身的 generation backend cache。
- 正在执行的任务不被强杀；新配置会在 worker 下一轮 idle/queue 检查时生效。
- `GenerationWorker.reload_limits()` 会保留 in-flight task，只调整后续调度池限制，避免破坏正在生成的任务。

### P3: 项目事件 source 语义恢复 worker 标记

原问题：

- 原 `ProjectEventService` 能区分 `worker`、`webui`、`filesystem`。
- 旧 IPC polling 通过重新构建项目快照并 diff，变更来源只区分：
  - 最近前端 mutation: `webui`
  - 其他文件变化: `filesystem`
- worker 子进程产生的项目变更无法在当前 polling 层保留为 `worker` source。

修复：

- `backend/utils/arcreel_desktop_sync.py` 新增轻量 JSONL journal，作为主进程与 worker 子进程之间的项目事件同步通道。
- 主进程和 worker 子进程都注册 `lib.project_change_hints.register_project_change_batch_listener(...)`。
- worker 内原有 `emit_project_change_batch(..., source="worker")` 会追加到 journal。
- 主进程项目事件 polling 先消费 journal；如果存在显式 batch，直接按原 source 返回 `changes` 事件。
- journal offset 在运行时启动时初始化到文件尾，避免重放旧会话事件；读取时按项目缓存未消费 batch，避免轮询 A 项目时吞掉 B 项目事件。

当前语义：

- worker 生成完成事件可恢复为 `source: "worker"`。
- 没有显式 journal batch 的文件变化仍按快照 diff fallback 为 `filesystem`。
- 前端最近 mutation 仍保留 `webui` source 兜底。

## 暂不视为问题的差异

以下差异符合当前封装约束，不作为缺失项：

- 登录页、JWT、Web auth store 移除。
- `/api-keys` 和 OpenClaw 单插件外部 API 移除。
- 浏览器下载 token 移除，导出改为桌面 IPC 返回二进制。
- 开发调试保留 `dev_mode: true`，继续走前端 dev server；`frontend/dist/index.html` 只作为生产构建 / 发布产物。

## 后续复查前提

后续如果继续审查或新增能力，应围绕以下目标判断是否产生新的执行语义差异：

- 保留 ArcReel 插件窗口内业务能力和界面体验。
- 通信方式替换为小蜗 IPC / 事件，但后端实际执行语义要尽量与原 ArcReel 一致。
- 普通生成任务继续复用原 task queue 和 worker 业务逻辑。
- 已解决的 Assistant 持久事件循环、provider 配置刷新、项目事件来源问题，不应在后续审查中重复作为未解决项；只有发现新行为差异时再单独记录。
