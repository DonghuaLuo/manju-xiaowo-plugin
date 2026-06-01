#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Handler 函数模块
所有 @sdk.handler 装饰的函数都放在这里
"""

from utils.xiaowo_sdk import sdk


def _emit_arcreel_events(result):
    """Push ArcReel stream payloads through Xiaowo's plugin event channel."""
    if isinstance(result, dict):
        for event in result.get("events") or []:
            sdk.send_event("arcreel_event", event)
    return result


@sdk.handler("hello")
def handle_hello(params):
    """演示 send_response - 简单请求响应"""
    name = params.get("name", "World")
    return {"message": f"Hello, {name}!", "from": "Python Backend"}


@sdk.handler("get_status")
def handle_get_status(params):
    """演示 send_response - 获取状态"""
    return {
        "status": "running",
        "plugin_id": sdk.plugin_id,
        "plugin_dir": sdk.plugin_dir
    }


@sdk.handler("arcreel_resource_request")
async def handle_arcreel_resource_request(params):
    """ArcReel 桌面资源入口：前端业务请求由小蜗 IPC 转到这里。"""
    from utils.arcreel_ipc_bridge import dispatch_desktop_resource_request

    return await dispatch_desktop_resource_request(params)


@sdk.handler("arcreel_event_subscribe")
async def handle_arcreel_event_subscribe(params):
    """ArcReel 任务/项目事件入口：返回初始快照。"""
    from utils.arcreel_ipc_bridge import build_event_snapshot

    return _emit_arcreel_events(await build_event_snapshot(params))


@sdk.handler("arcreel_event_poll")
async def handle_arcreel_event_poll(params):
    """ArcReel 任务/项目事件入口：按游标拉取任务/项目变更事件。"""
    from utils.arcreel_ipc_bridge import poll_event_streams

    return _emit_arcreel_events(await poll_event_streams(params))


@sdk.handler("arcreel_local_file_request")
async def handle_arcreel_local_file_request(params):
    """ArcReel 本地文件资源入口：前端传本地路径，后端主进程读取文件。"""
    from utils.arcreel_ipc_bridge import dispatch_desktop_file_request

    return await dispatch_desktop_file_request(params)


@sdk.handler("arcreel_read_local_file")
def handle_arcreel_read_local_file(params):
    """读取桌面对话框选中的本地文件，用于需要 data URL 的前端兼容点。"""
    from utils.arcreel_ipc_bridge import read_local_file_base64

    return read_local_file_base64(params)


@sdk.handler("arcreel_asset_roots")
def handle_arcreel_asset_roots(params):
    """返回 ArcReel 本地资产根目录，供前端直接用 convertFileSrc 加载媒体。"""
    from lib.app_data_dir import app_data_dir

    projects_root = app_data_dir()
    return {
        "projects_root": str(projects_root),
        "global_assets_root": str(projects_root / "_global_assets"),
    }


@sdk.handler("arcreel_resolve_media_path")
def handle_arcreel_resolve_media_path(params):
    """解析 /api/files 等媒体资源到本地文件路径，避免经 IPC 传输二进制。"""
    from utils.arcreel_ipc_bridge import resolve_media_path

    return resolve_media_path(params)


@sdk.handler("arcreel_save_diagnostics")
async def handle_arcreel_save_diagnostics(params):
    """桌面诊断包导出：前端选择目标路径后，后端直接写入 ZIP。"""
    from utils.arcreel_ipc_bridge import save_diagnostics_archive

    return await save_diagnostics_archive(params)


@sdk.handler("arcreel_start_project_archive_export")
async def handle_arcreel_start_project_archive_export(params):
    """桌面项目导出：前端选择目标路径后，后端异步直接写入 ZIP。"""
    from utils.arcreel_ipc_bridge import start_project_archive_export

    return await start_project_archive_export(params)


@sdk.handler("arcreel_asset_archive_export_info")
async def handle_arcreel_asset_archive_export_info(params):
    """桌面资产导出：返回全局资产导出所需路径信息。"""
    from utils.arcreel_ipc_bridge import asset_archive_export_info

    return await asset_archive_export_info(params)


@sdk.handler("arcreel_start_asset_archive_export")
async def handle_arcreel_start_asset_archive_export(params):
    """桌面资产导出：前端选择目标路径后，后端异步直接写入 ZIP。"""
    from utils.arcreel_ipc_bridge import start_asset_archive_export

    return await start_asset_archive_export(params)


@sdk.handler("arcreel_export_task_status")
async def handle_arcreel_export_task_status(params):
    """查询桌面导出任务状态。"""
    from utils.arcreel_ipc_bridge import get_export_task_status

    return await get_export_task_status(params)


@sdk.handler("arcreel_open_desktop_path")
async def handle_arcreel_open_desktop_path(params):
    """打开本机文件或目录所在位置。"""
    from utils.arcreel_ipc_bridge import open_desktop_path

    return await open_desktop_path(params)


@sdk.handler("arcreel_detect_jianying_draft_root")
async def handle_arcreel_detect_jianying_draft_root(params):
    """尝试自动探测本机剪映草稿目录。"""
    from utils.arcreel_ipc_bridge import detect_jianying_draft_root

    return await detect_jianying_draft_root(params)


@sdk.handler("arcreel_start_jianying_draft_export")
async def handle_arcreel_start_jianying_draft_export(params):
    """桌面剪映草稿导出：后端异步直接写入剪映草稿目录。"""
    from utils.arcreel_ipc_bridge import start_jianying_draft_export

    return await start_jianying_draft_export(params)


@sdk.handler("long_task")
def handle_long_task(params):
    """非阻塞长任务示例。

    真实 ArcReel 长任务应走任务表 / worker 进程。这里仅保留兼容 demo，
    不再用 sleep 占住 stdin/stdout IPC 主循环。
    """
    total = params.get("total", 5)
    sdk.send_event("progress", {"current": 0, "total": total, "percent": 0, "status": "queued"})
    return {"success": True, "task_id": "demo-task", "status": "queued"}
