# ArcReel 小蜗插件封装审查约束

本文档用于审查 `plugins/manju` 将 ArcReel WebUI 封装为小蜗桌面插件时的判断口径。

## 核心目标

我们的目标不是继续运行一个 ArcReel Web 服务，而是把 ArcReel 的插件内业务能力和界面体验封装进小蜗桌面插件。

- ArcReel 原来是 WebUI，通过 HTTP / SSE 和 FastAPI 后端通信。
- 小蜗插件是桌面软件，前端与插件后端通过小蜗 IPC / Tauri 事件通信。
- 审查时应确认“插件内功能和任务执行语义保持一致”，而不是机械保留 Web 服务形态。

## 必须保留

- ArcReel 插件窗口内用户可见的业务能力和界面体验。
- 项目创建、导入、源文件上传、素材管理、配置、生成任务、任务状态、导出、Assistant 等插件内工作流。
- 文件拖拽体验；桌面环境下可用 `xiaowo-sdk` 的 file-drop 路径事件或本地文件读取能力完成适配。
- ArcReel 原 Assistant Markdown 渲染体验；默认保留 `streamdown` 依赖和组件逻辑，只有它与单文件生产构建明确冲突时才允许降级。
- 黑白主题、多语言、自定义标题栏等小蜗插件要求。
- `plugins/manju/frontend/src/components/TitleBar.tsx` 的视觉、按钮、事件语义不得改变。
- 开发调试继续走前端 dev server；`frontend/dist/index.html` 只作为生产构建 / 发布产物。

## 不作为缺失项

以下属于 ArcReel Web 服务对外能力，不要求在单个小蜗插件里保留：

- 登录页、JWT、Web auth store。
- 浏览器下载 token。
- `/api-keys` 管理页和 API Key CRUD。
- OpenClaw 专用入口或单插件独立外部 API。

小蜗体系里的外部 CLI、导入使用、MCP 调用统一通过 `xiaowo-cli` 服务所有插件，不为 `manju` 单独做一套外部 API。

## 通信替换要求

- 普通业务请求可以保持前端 ArcReel `API` 方法形态，但底层应从 `fetch('/api/v1/...')` 转为 `PluginSDK.callBackend(...)` 或被运行时适配层拦截到 IPC。
- 插件后端应尽量复用 ArcReel 原 router/service/task 逻辑，避免重写业务语义。
- SSE / EventSource 需要映射到小蜗后端事件或轮询事件，并尽量保持原事件名和 payload：Assistant `snapshot`、`patch`、`delta`、`question`、`compact`、`status`，以及任务 `snapshot` / `task`、项目 `changes` 等。
- Assistant 事件适配应优先复用 ArcReel 原 `AssistantService` 的 projector / live message dispatch 语义，不应把所有增量都粗暴降级成全量 snapshot。
- 文件上传需要同时兼容桌面对话框路径、SDK file-drop 路径和浏览器拖拽 `File`；路径型文件走本地路径，浏览器 `File` 只作为桌面拖拽不可取得路径时的兜底。

## 后端并发约束

- 不使用 `threading.Thread(target=worker); t.start()` 承载后台任务。
- 长任务优先走 ArcReel 原任务表 / worker 进程 / async 机制。
- 需要独立执行时使用子进程或现有队列 worker，并通过事件或轮询同步状态。

## 审查结论口径

判断一个差异是否需要修复时，先问：

1. 这个差异是否影响插件窗口内用户可见业务能力或体验？
2. 这个差异是否改变了 ArcReel 原业务任务最终调用的 service/router/worker 语义？
3. 这个差异是否只是 Web 服务对外接口被桌面 IPC 替代？

若答案属于第 1 或第 2 类，应修复或讨论；若只是第 3 类，一般不视为缺失。
