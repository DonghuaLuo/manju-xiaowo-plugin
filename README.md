# Manju Xiaowo Plugin

`manju` 是小蜗的 AI 短剧 / 漫剧生成插件，基于 [ArcReel](https://github.com/ArcReel/ArcReel) 封装为小蜗桌面插件。

## 在小蜗中部署使用

小蜗插件开发者文档：<https://www.xiaowoai.com/ask/devdoc>

当前仓库是小蜗工具的插件源码，插件根目录就是小蜗插件目录中的一个插件。例如当前插件目录名为 `manju`，对应 `manifest.json` 中的：

```json
{
  "id": "manju"
}
```

小蜗加载插件时会把插件目录名作为插件 ID 使用，因此插件目录名必须和 `manifest.json` 里的 `id` 保持一致。

如果要把这个插件放到已安装的小蜗中使用，建议不要直接覆盖已有的 `manju` 插件，而是改成一个新的插件名，例如 `manju-dev` 或 `manju-local`：

1. 将整个插件目录复制到小蜗安装目录的 `plugins` 目录中，例如：

   ```text
   <小蜗安装目录>\plugins\manju-dev
   ```

2. 修改复制后目录中的 `manifest.json`，让 `id` 和目录名一致：

   ```json
   {
     "id": "manju-dev"
   }
   ```

3. 在 `manifest.json` 中开启开发者模式：

   ```json
   {
     "dev_mode": true
   }
   ```

4. 确认 `dev.frontend.entry` 指向当前前端开发服务地址。当前插件默认使用：

   ```json
   {
     "dev": {
       "frontend": {
         "entry": "http://localhost:5174"
       }
     }
   }
   ```

5. 启动前端开发服务：

   ```powershell
   cd <小蜗安装目录>\plugins\manju-dev\frontend
   pnpm install
   pnpm dev
   ```

   如果 Vite 实际启动端口不是 `5174`，需要同步修改 `manifest.json` 中的 `dev.frontend.entry`。

6. 重新启动小蜗，或在小蜗中重新扫描 / 打开插件。

这样处理可以避免和小蜗中已有的 `manju` 插件 ID 冲突，也能让小蜗按开发者模式加载本地前端开发服务和插件后端配置。

## 配置清单要点

- 插件目录名必须和 `manifest.json` 的 `id` 一致。
- `dev_mode: true` 时，小蜗会使用 `dev.frontend.entry` 加载前端，适合源码调试和本地部署。
- `dev_mode: false` 时，小蜗会使用 `frontend.entry`，也就是打包后的 `frontend/dist/index.html`。
- 本插件依赖扩展模型 / 运行时检查，首次加载项目列表时会根据 `manifest.json` 中的 `extmodels.check_files` 检查所需文件。
- 修改插件 ID 后，桌面快捷方式、窗口标签、插件数据隔离都会按新的 ID 生效。

## 运维与自动化方案

- [Agent 自迭代执行方案](backend/agent_ops/execution-plan.md)
- [Agent 运维自动化入口](backend/agent_ops/README.md)

## License

This plugin includes ArcReel-derived code licensed under the GNU Affero General Public License v3.0.

本插件包含 ArcReel 派生源码，按 GNU Affero General Public License v3.0 开源。许可证正文见：

- [LICENSE](LICENSE)
- [LICENSES/LICENSE.txt](LICENSES/LICENSE.txt)
- [backend/LICENSE](backend/LICENSE)

## Source And Attribution

- 上游项目：<https://github.com/ArcReel/ArcReel>
- 插件源码 GitHub：<https://github.com/DonghuaLuo/manju-xiaowo-plugin>
- 插件源码 Gitee：<https://gitee.com/donghuax/manju-xiaowo-plugin>
- 版权归属：[LICENSES/COPYRIGHT.txt](LICENSES/COPYRIGHT.txt)
- 小蜗侧修改说明：[LICENSES/CHANGES-XIAOWO.md](LICENSES/CHANGES-XIAOWO.md)
- 源码提供说明：[LICENSES/SOURCE-OFFER.md](LICENSES/SOURCE-OFFER.md)

本仓库公开的是 `manju` 插件源码。小蜗主程序和其他插件是独立项目，不包含在本插件源码仓库内。
