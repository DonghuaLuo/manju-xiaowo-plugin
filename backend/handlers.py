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
def handle_arcreel_resource_request(params):
    """ArcReel 桌面资源入口：前端业务请求由小蜗 IPC 转到这里。"""
    from utils.arcreel_ipc_bridge import dispatch_desktop_resource_request

    return dispatch_desktop_resource_request(params)


@sdk.handler("arcreel_event_subscribe")
def handle_arcreel_event_subscribe(params):
    """ArcReel 任务/项目事件入口：返回初始快照。"""
    from utils.arcreel_ipc_bridge import build_event_snapshot

    return _emit_arcreel_events(build_event_snapshot(params))


@sdk.handler("arcreel_event_poll")
def handle_arcreel_event_poll(params):
    """ArcReel 任务/项目事件入口：按游标拉取任务/项目变更事件。"""
    from utils.arcreel_ipc_bridge import poll_event_streams

    return _emit_arcreel_events(poll_event_streams(params))


@sdk.handler("arcreel_local_file_request")
def handle_arcreel_local_file_request(params):
    """ArcReel 本地文件资源入口：前端传本地路径，后端主进程读取文件。"""
    from utils.arcreel_ipc_bridge import dispatch_desktop_file_request

    return dispatch_desktop_file_request(params)


@sdk.handler("arcreel_read_local_file")
def handle_arcreel_read_local_file(params):
    """读取桌面对话框选中的本地文件，用于需要 data URL 的前端兼容点。"""
    from utils.arcreel_ipc_bridge import read_local_file_base64

    return read_local_file_base64(params)


@sdk.handler("arcreel_download_diagnostics")
def handle_arcreel_download_diagnostics(params):
    """桌面诊断包导出：返回 ZIP 数据，不走旧 Web 下载端点。"""
    from utils.arcreel_ipc_bridge import download_diagnostics_blob

    return download_diagnostics_blob(params)


@sdk.handler("arcreel_export_project_archive")
def handle_arcreel_export_project_archive(params):
    """桌面项目导出：返回 ZIP 数据和诊断信息，不暴露浏览器下载 token。"""
    from utils.arcreel_ipc_bridge import export_project_archive_blob

    return export_project_archive_blob(params)


@sdk.handler("arcreel_export_jianying_draft")
def handle_arcreel_export_jianying_draft(params):
    """桌面剪映草稿导出：返回 ZIP 数据，不走浏览器下载 URL。"""
    from utils.arcreel_ipc_bridge import export_jianying_draft_blob

    return export_jianying_draft_blob(params)


@sdk.handler("long_task")
def handle_long_task(params):
    """非阻塞长任务示例。

    真实 ArcReel 长任务应走任务表 / worker 进程。这里仅保留兼容 demo，
    不再用 sleep 占住 stdin/stdout IPC 主循环。
    """
    total = params.get("total", 5)
    sdk.send_event("progress", {"current": 0, "total": total, "percent": 0, "status": "queued"})
    return {"success": True, "task_id": "demo-task", "status": "queued"}
