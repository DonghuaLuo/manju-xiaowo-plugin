# Agent 自迭代执行方案

## 背景

Manju 当前大量自动化能力依赖固定脚本、固定解析器和固定接口适配。例如发布脚本、供应商调用解析、结构化输出解析、生成流程 preflight 等。这类方案的优点是可重复、可测试、可审计，但近期反复出现的问题也很清楚：

- 供应商接口和中转网关能力变化快，固定脚本很容易落后。
- 脚本失败后，agent 往往只是报告失败，而不是继续诊断、修复、验证并沉淀新版本。
- 同一个问题会被多次修补，但缺少“失败样例 -> 修复脚本 -> 回归测试 -> 版本记录”的闭环。
- 用户真正需要的是任务完成，而不是执行某个既定脚本本身。

因此，后续应把固定脚本从“唯一执行者”改为“agent 可调用、可修复、可版本化的工具层”。Agent 负责理解目标、判断脚本是否适用、在失败时生成或修复脚本，并把通过验证的新脚本沉淀为下一次默认版本。

## 结论

最稳定的方案不是“完全固定脚本”，也不是“完全自由 agent”，而是：

**受控的 agent 自迭代脚本体系。**

固定脚本仍然保留，作为稳定入口和已验证路径；agent 作为监督者和修复者，在脚本无法完成任务时进入诊断、改造和验证流程。通过测试的新脚本版本才会成为下一次默认路径。

## 三种方案对比

| 方案 | 优点 | 风险 | 稳定性判断 |
| --- | --- | --- | --- |
| 固定脚本方案 | 可重复、速度快、容易审计 | 供应商变化或边界变化后容易失效；失败后不会自我修复 | 对稳定场景可靠，对变化场景脆弱 |
| 纯 agent 方案 | 理解能力强，能处理未知问题 | 不确定性高，容易边界漂移，结果难复现 | 不适合作为生产默认路径 |
| 受控自迭代脚本方案 | 保留脚本可复现性，同时让 agent 自动诊断和修复 | 需要版本、测试、回滚和权限边界 | 最适合 Manju 这类复杂生成流程 |

## 核心原则

1. **任务目标优先，不是脚本优先。**
   脚本只是完成任务的工具。脚本失败时，agent 应继续查明原因，而不是把失败当作最终结果。

2. **所有脚本都必须版本化。**
   新脚本或修复后的脚本必须记录版本、适用场景、输入输出契约、失败样例和验证结果。

3. **agent 可以修脚本，但不能无边界修改运行环境。**
   默认只在当前 Manju 后端根目录内修改和验证，不直接修改已安装插件目录中的运行副本。

4. **验证通过才升级默认版本。**
   一个修复必须至少包含：复现失败、实现修复、增加回归测试、通过目标测试。

5. **外部 API 适配必须基于证据。**
   官方供应商以官方文档为准；自定义供应商和中转网关以官方 GitHub 文档或源码为准。不能猜接口字段和返回结构。

## 推荐架构

```text
用户任务
  |
  v
Agent 任务控制器
  |
  +-- 读取当前任务目标、项目状态、模型配置、历史失败记录
  |
  +-- 调用当前默认脚本版本
  |     |
  |     +-- 成功 -> 记录结果
  |     |
  |     +-- 失败 -> 生成 repair task 并进入诊断流程
  |
  +-- 诊断流程
        |
        +-- 收集日志、输入、输出、供应商响应、源码路径
        +-- 对照本地 API 证据文档或官方资料
        +-- 启动运维 agent 命令生成脚本补丁或新脚本版本
        +-- 增加失败样例回归测试
        +-- 运行验证
        +-- 通过后提升为默认版本
        +-- 失败则保留报告，不替换默认版本
```

## 脚本版本记录格式

每个 agent 可迭代脚本都应有版本记录。建议记录到对应脚本旁边的 Markdown 或 JSON 元数据中。

```text
script_id: text_structured_output_probe
version: 1.2.0
owner: manju-agent-tools
status: default
created_at: 2026-06-10
source_failure:
  - custom-1/gpt-5.5 返回 {"episode":1}，不符合 DramaEpisodeScript schema
evidence:
  - docs/provider-api-evidence/api-interface-matrix.md
  - docs/provider-api-evidence/call-paths-and-custom-providers.md
tests:
  - tests/test_text_structured_probe.py
  - tests/test_openai_text_backend.py
rollback:
  - revert to version 1.1.0
notes:
  - probe 必须使用对抗式 prompt，不能用合法样例 prompt
```

## 执行闭环

### 1. 运行当前版本

Agent 首先运行当前默认脚本或调用链，例如：

- 发布：`release_plugins.py`
- 结构化输出能力检查：`probe_text_structured_output_backend`
- 剧本生成：`generate_episode_script`
- 供应商模型发现：custom provider discovery

### 2. 判断失败类型

失败不能只记录为“执行失败”，应分类：

- 脚本自身错误：参数、路径、编码、依赖、版本。
- 上游接口错误：认证、限流、模型不存在、schema 不支持。
- 解析错误：返回格式变化、字段缺失、schema 不匹配。
- 环境错误：运行目录、Python runtime、前端构建、发布配置。
- 数据错误：项目文件缺失、历史缓存污染、输入不满足前置条件。

### 3. 诊断和证据对齐

Agent 应读取：

- 当前源码调用链。
- 本地 API 证据文档。
- 失败日志和最小复现输入。
- 必要时再查官方文档或官方 GitHub 源码。

对于供应商调用，禁止只靠模型名或历史经验推断接口能力。

### 4. 生成修复版本

修复方式可以是：

- 修改现有脚本。
- 新增能力 probe。
- 增加 endpoint capability 记录。
- 调整解析器。
- 增加 preflight。
- 增加降级流程，但必须明确标记为非 strict，不得伪装成 strict schema。

### 5. 验证

验证至少包含：

- 失败样例能被捕获。
- 成功样例仍能通过。
- 相关调用链不回归。
- `git diff --check` 通过。

对于 Manju 文本模型结构化输出问题，最低验证集应包含：

- `tests/test_text_structured_probe.py`
- `tests/test_openai_text_backend.py`
- `tests/test_text_backend_factory.py`
- `tests/test_custom_provider_factory.py`
- 涉及总览或剧本时补 `tests/test_script_generator.py`

### 6. 提升默认版本

只有验证通过后，才允许把新脚本版本标记为默认版本。失败版本保留为实验记录，不进入默认路径。

## 对 Manju 当前问题的落地方式

结构化输出问题不应只靠一次代码修复。它应该作为首个 agent 自迭代脚本体系的试点：

1. 建立 `text_structured_output_probe` 版本记录。
2. 记录当前修复原则：自定义 `openai-chat` 必须真实发送 `response_format.type=json_schema`。
3. probe 必须使用对抗式 prompt，确认 endpoint 是否真的执行 schema。
4. 脚本生成和项目总览生成前都必须经过 preflight。
5. 供应商能力应逐步沉淀为状态：`unknown`、`supported`、`unsupported`、`schema_not_enforced`。
6. 后续每次遇到新供应商或新网关异常时，先新增失败样例，再修复 probe 或 endpoint 适配。

## 需要保留的人工边界

Agent 可以自动做：

- 读取源码和文档。
- 运行测试和复现。
- 修改开发仓脚本。
- 生成版本记录。
- 给出提交建议。

Agent 不应自动做：

- 直接修改已安装插件目录中的 `plugins/manju` 运行副本。
- 在未验证时替换默认脚本。
- 把不支持 strict schema 的结果包装成 strict 成功。
- 对供应商 API 字段做无证据猜测。
- 跳过测试直接发布。

## 最小可行版本

第一阶段只做轻量落地：

- 新增一个脚本版本记录目录。
- 每个可迭代脚本记录 `script_id`、`version`、`status`、`tests`、`known_failures`。
- Agent 修复脚本后必须同步更新记录。
- 先覆盖结构化输出 probe、发布流程、供应商模型发现三类高频失败点。

当前落地位置：

- `backend/agent_ops/README.md`
- `backend/agent_ops/registry/*.json`
- `backend/agent_ops/registry/failure-examples/*.json`
- `backend/agent_ops/registry/stable/*.json`
- `backend/agent_ops/scripts/agent_script_registry.py`
- `backend/agent_ops/tests/test_agent_script_registry.py`

运行目录约定：

- 插件后端进程的当前工作目录是后端根目录。
- `agent_ops` 位于后端根目录下。
- 从插件后端进程调用 agent 脚本时，入口使用 `agent_ops\scripts\agent_script_registry.py`。
- 脚本内部通过自身文件位置反推出后端根目录，再定位 `agent_ops/registry`、`agent_ops/tests`、`tests` 和 `docs`，不依赖调用者当前目录。
- registry 中的 `{python}` / `{python_executable}` 在执行时展开为运行 registry 的 Python 可执行文件；由插件后端进程启动时，它就是当前插件后端使用的 Python。

第二阶段自动化入口：

- 脚本 registry 校验：`{python} agent_ops\scripts\agent_script_registry.py validate`
- 脚本 registry 列表：`{python} agent_ops\scripts\agent_script_registry.py list`
- 失败样例库：`{python} agent_ops\scripts\agent_script_registry.py failure-examples`
- 一键运行最新默认脚本：`{python} agent_ops\scripts\agent_script_registry.py run <script_id>`
- 失败后启动运维 agent 修复并复跑：`{python} agent_ops\scripts\agent_script_registry.py run <script_id> --repair-on-failure --agent-command "<agent-command> {repair_task}"`
- 候选版本失败回滚：`{python} agent_ops\scripts\agent_script_registry.py run <script_id> --rollback-on-failure`
- 候选版本成功沉淀：`{python} agent_ops\scripts\agent_script_registry.py run <script_id> --snapshot-on-success`
- 稳定快照：`{python} agent_ops\scripts\agent_script_registry.py snapshot --all-defaults`
- 回滚机制：`{python} agent_ops\scripts\agent_script_registry.py rollback <script_id>`，或 `{python} agent_ops\scripts\agent_script_registry.py run <script_id> --rollback-on-failure`

失败处理顺序：

1. `run` 先执行当前 default 记录的自动验证命令。
2. 命令失败时，`--repair-on-failure` 会生成 `agent_ops/repair-runs/*.json` 修复任务，里面包含失败命令、输出尾部、源码路径、证据路径、测试路径、失败样例、成功标准和 `repair_write_allowlist`。
3. registry 启动 `--agent-command` 指定的运维 agent 命令，并把 `{repair_task}` 展开为修复任务文件路径。
4. 运维 agent 只能修改 `repair_write_allowlist` 声明的范围；未声明时默认只能改 `agent_ops`。
5. registry 在运维 agent 启动前后做文件快照，发现越界修改就直接失败，不复跑验证，也不写入稳定快照。
6. agent 修改脚本、registry 或测试后，registry 自动复跑该 default 记录的验证命令。
7. 复跑通过后，可配合 `--snapshot-on-success` 写入新的稳定快照；复跑仍失败时，可配合 `--rollback-on-failure` 恢复到最近稳定快照。

这里的回滚只用于候选修复失败后的保护，不是失败处理的终点。正常闭环应优先生成 repair task、启动 agent 修复、复跑验证；只有修复失败或需要恢复默认可用状态时才回滚。

运维 agent 和创作 agent 的权限边界不同：

- 创作 agent 面向项目内容生成，cwd 绑定到 `projects/<project>`，不允许写 cwd 外路径，也不允许直接写代码扩展名。
- 运维 agent 面向脚本和后端调用链修复，由 `agent_ops` registry 启动；它的修改必须落在 `repair_write_allowlist` 内。
- `agent_ops` 自身可作为所有运维修复的默认写入范围；业务源码、测试和证据文档必须按脚本记录逐项声明。

## 评估标准

这个方案是否稳定，不能看“agent 是否聪明”，而要看闭环是否存在：

- 能不能复现失败。
- 能不能定位到脚本或接口边界。
- 能不能产出可审计的新版本。
- 能不能用测试证明修复。
- 能不能回滚。
- 能不能把同类问题沉淀成下一次默认能力。

只要这些条件成立，受控自迭代脚本方案会比当前纯固定脚本方案更稳定，也更符合 agent 的优势。
