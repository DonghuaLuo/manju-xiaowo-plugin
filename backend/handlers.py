#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Handler 函数模块
所有 @sdk.handler 装饰的函数都放在这里
"""

from utils.xiaowo_sdk import sdk
from utils.manju_ipc_api import register_manju_api_handlers


register_manju_api_handlers(sdk)


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


@sdk.handler("long_task")
def handle_long_task(params):
    """非阻塞长任务示例。

    真实 ArcReel 长任务应走任务表 / worker 进程。这里仅保留兼容 demo，
    不再用 sleep 占住 stdin/stdout IPC 主循环。
    """
    total = params.get("total", 5)
    sdk.send_event("progress", {"current": 0, "total": total, "percent": 0, "status": "queued"})
    return {"success": True, "task_id": "demo-task", "status": "queued"}
