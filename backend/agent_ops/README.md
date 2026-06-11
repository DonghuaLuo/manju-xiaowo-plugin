# Agent Ops

本目录保存给 agent / 运维自动化执行的脚本、约束文档、registry、失败样例和稳定快照。目录位于 Manju 插件后端根目录内，默认从后端当前工作目录执行。

每个 JSON 文件记录一个可由 agent 调用、修复和迭代的脚本或调用链。记录必须能回答：

- 当前默认版本是什么。
- 入口在哪里。
- 修复时应该看哪些源码和证据文档。
- 已知失败类型和失败样例有哪些。
- 验证命令和回归测试是什么。
- 如果新版本失败，如何回滚。

`registry/*.json` 的验证命令可使用 `{python}` / `{python_executable}` 占位符。执行时 `agent_script_registry.py` 会把它替换为运行 registry 的 Python；由插件后端进程启动时，它就是当前插件后端使用的 Python。下面命令都从插件后端运行目录执行；手工调试时，用当前插件后端 Python 替换 `{python}`。

插件后端也提供 `manju_api_run_agent_ops` 调用入口。该入口固定使用当前后端进程的 `sys.executable`，并以插件后端根目录作为运行目录启动 `agent_ops/scripts/agent_script_registry.py`；IPC 只开放 `validate`、`list`、`failure-examples` 和必须带 `dry_run=true` 的 `run` 预览，不开放 repair、rollback、snapshot 或 repair agent 启动能力，也不允许调用方传 Python 路径。

运行时自动处理：关键 agent 工具失败时可由后端直接触发 `utils/agent_ops_autofix.py`，自动写入 `agent_ops/repair-runs` 修复任务并运行对应 registry 检查。默认会使用当前 Manju 后端的 Claude Agent SDK 凭据自动启动内置修复 agent；若运行环境配置了 `MANJU_AGENT_OPS_AGENT_COMMAND`，该命令仅作为开发/运维覆盖项。修复 agent 的写入范围按 registry 记录的 `repair_write_allowlist` 校验，越界修改会被恢复。可用 `MANJU_AGENT_OPS_AUTO_REPAIR=0` 临时关闭自动触发。

校验命令：

```powershell
{python} agent_ops\scripts\agent_script_registry.py validate
```

查询默认脚本：

```powershell
{python} agent_ops\scripts\agent_script_registry.py list
```

查询失败样例：

```powershell
{python} agent_ops\scripts\agent_script_registry.py failure-examples
```

一键运行某个默认脚本的自动验证命令：

```powershell
{python} agent_ops\scripts\agent_script_registry.py run text_structured_output_probe
```

验证候选修复版本并在失败时自动回滚到最近的稳定快照：

```powershell
{python} agent_ops\scripts\agent_script_registry.py run text_structured_output_probe --rollback-on-failure
```

验证失败时生成修复任务并启动运维 agent 命令，agent 修复后自动复跑验证：

```powershell
{python} agent_ops\scripts\agent_script_registry.py run text_structured_output_probe --repair-on-failure --agent-command "<agent-command> {repair_task}"
```

`--agent-command` 是运行时传入的运维 agent 命令模板，不在 registry 中固定。可用占位符包括 `{repair_task}`、`{python}`、`{python_executable}`、`{script_id}`、`{version}` 和 `{failed_command}`。

验证候选修复版本并在成功后写入当前版本稳定快照：

```powershell
{python} agent_ops\scripts\agent_script_registry.py run text_structured_output_probe --snapshot-on-success
```

先查看将要执行的命令，不真正运行：

```powershell
{python} agent_ops\scripts\agent_script_registry.py run text_structured_output_probe --dry-run
```

保存当前默认版本为稳定快照：

```powershell
{python} agent_ops\scripts\agent_script_registry.py snapshot --all-defaults
```

回滚某个脚本记录到最新稳定快照：

```powershell
{python} agent_ops\scripts\agent_script_registry.py rollback text_structured_output_probe
```

规则：

- `status` 为 `default` 的记录才是下一次任务的默认路径。
- `validate` 是完整落地态检查，要求当前 default 版本已有稳定快照，且快照内容与当前记录一致。
- `run` 是候选验证入口，允许当前 default 版本还没有同版本稳定快照；失败时可用 `--rollback-on-failure` 回到最近旧稳定版本，成功后可用 `--snapshot-on-success` 写入新稳定快照。
- `--repair-on-failure` 不是回滚；它会把失败命令、输出尾部、源码/证据/测试路径写入 `agent_ops/repair-runs`，再启动 `--agent-command` 指定的运维 agent 命令，agent 修复后复跑验证。
- 运维 agent 的写入范围由 registry 记录的 `repair_write_allowlist` 声明；未声明时默认只允许修改 `agent_ops`。
- registry 会在运维 agent 启动前后做文件快照，若发现它修改了 `repair_write_allowlist` 之外的后端源码文件，本次修复失败，且不会继续复跑验证或写入稳定快照。
- `agent_ops/repair-runs` 是运行时痕迹，不作为正式 registry 记录提交。
- `source_files`、`evidence`、`tests` 中的相对路径必须能从后端根目录解析。
- `failure_examples` 必须指向 `agent_ops/registry/failure-examples` 下的样例，并且样例的 `script_id` 必须与脚本记录一致。
- `agent_ops/registry/stable` 保存已验证默认版本的稳定快照，回滚只从这里恢复。
- `manual:` 开头的测试项表示人工或发布期验证，不做文件存在性检查。
- `run` 默认跳过 `manual:` 命令，避免普通验证误触发发布等外部副作用。
- 修改脚本或调用链后，必须同步更新对应 JSON 记录。
