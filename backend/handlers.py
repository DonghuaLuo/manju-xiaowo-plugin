#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Handler 函数模块
所有 @sdk.handler 装饰的函数都放在这里
"""

import time
from utils.xiaowo_sdk import sdk
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
    """演示 send_event - 长任务进度推送"""
    total = params.get("total", 5)

    for i in range(total):
        time.sleep(1)  # 模拟耗时操作
        percent = int((i + 1) / total * 100)
        print(percent)
        # 使用 send_event 主动推送进度
        sdk.send_event("progress", {"current": i + 1, "total": total, "percent": percent})

    # 最后通过 send_response 返回结果
    return {"success": True, "message": f"完成 {total} 个任务"}