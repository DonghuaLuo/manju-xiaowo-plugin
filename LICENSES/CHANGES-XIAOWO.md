# 小蜗侧修改说明

## 基本信息

- 插件 ID：`manju`
- 插件名称：`AI 短剧 / 漫剧生成`
- 上游项目：`ArcReel`
- 上游仓库：<https://github.com/ArcReel/ArcReel>
- 上游许可证：GNU Affero General Public License v3.0
- 上游参考 commit：`825bb060868ddf18db33eaeb1607cee486451142`
- 上游版本：`0.14.0`（见 `backend/pyproject.toml`）
- 修改 / 集成日期：2026-05-20

## 是否直接修改上游源码

是。

本插件将 ArcReel 作为小蜗插件源码的一部分重新组织和分发，并新增小蜗插件运行所需的清单、前端窗口、JSON-RPC 后端入口和 SDK 适配层。为避免低估 AGPL-3.0 下的源码提供义务，`manifest.json` 中的 `open_source.upstream_source_modified` 保守标记为 `true`。

## 小蜗侧改动范围

相对 ArcReel 上游发布形态，小蜗侧主要做了以下封装和适配：

1. 将 ArcReel 源码放入插件仓库的 `backend/` 目录，作为 `manju` 插件的后端主体。
2. 新增 `manifest.json`，声明插件 ID、标题、窗口配置、Python 后端入口、运行时配置和开源元数据。
3. 新增外层 `frontend/`，提供小蜗插件窗口、标题栏、主题、许可证入口和与小蜗主应用集成的前端壳。
4. 新增 `backend/main.py`、`backend/handlers.py`、`backend/utils/`，用于小蜗 Python 插件后端的 JSON-RPC 通信和 SDK 适配。
5. 新增 `LICENSES/`，保留许可证原文、版权归属、NOTICE、源码提供说明和本修改说明。
6. 维护独立插件仓库，并同时配置 GitHub / Gitee 远程镜像，方便满足 AGPL-3.0 下的源码获取需求。

## 源码提供范围

本仓库公开的是 `manju` 插件源码，包括 ArcReel-derived 后端、小蜗插件前端壳、插件 manifest、后端适配层和许可证材料。

小蜗主程序和其他插件是独立项目，不属于本插件仓库的源码范围。

## 许可证保留

本插件保留以下许可证材料：

- `LICENSE`
- `LICENSES/LICENSE.txt`
- `backend/LICENSE`
- `LICENSES/NOTICE.txt`
- `LICENSES/COPYRIGHT.txt`
- `LICENSES/SOURCE-OFFER.md`

分发本插件、打包本插件或让用户通过网络访问本插件功能时，应保留以上文件，并提供对应版本的完整插件源码获取方式。
