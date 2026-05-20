#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小蜗工具 - 插件后端 SDK
封装stdin/stdout JSON-RPC 安全通信协议
"""

import sys
import json
import os
import base64
from typing import Callable, Dict, Any, Optional

# Ed25519 签名验证
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


# ============================================================
# 公钥配置（Base64 编码的 Ed25519 公钥，32 字节）
# ============================================================


def _create_sdk_with_protected_verifier():
    """
    创建带有受保护验证器的 SDK 实例
    handlers 和验证逻辑都封装在闭包中，外部无法访问
    """

    # ========== 闭包内部的私有数据 ==========
    public_key=""
    _handlers: Dict[str, Callable] = {}  # handlers 在闭包中，外部无法访问
    _verify_key = None
    _key_init_failed=False
    if public_key:
        try:
            _verify_key = VerifyKey(base64.b64decode(public_key))
        except Exception as e:
            _key_init_failed=True
            sys.stderr.write(f"初始化公钥失败: {e}\n")
            sys.stderr.flush()

    def _internal_verify(msg_id: int, method: str, params: Any, token: Optional[str]) -> bool:
        """内部验证函数，完全封装在闭包中"""
        # 公钥配置了但初始化失败，拒绝所有请求
        if _key_init_failed:
            sys.stderr.write("Token 验证失败: 公钥配置无效\n")
            sys.stderr.flush()
            return False
        # public_key 为 None 时，_verify_key 为 None，跳过验证（向后兼容）
        if not _verify_key:
            return True
        if not token:
            sys.stderr.write("Token 验证失败: 缺少 token\n")
            sys.stderr.flush()
            return False
        try:
            params_json = json.dumps(params, ensure_ascii=False, separators=(',', ':'))
            message = f"{msg_id}|{method}|{params_json}"
            signature = base64.b64decode(token)
            _verify_key.verify(message.encode('utf-8'), signature)
            return True
        except BadSignatureError:
            sys.stderr.write("Token 验证失败: 签名无效\n")
            sys.stderr.flush()
            return False
        except Exception as e:
            sys.stderr.write(f"Token 验证失败: {e}\n")
            sys.stderr.flush()
            return False

    # ========== SDK 类定义 ==========
    class _PluginSDK:
        """插件后端 SDK"""

        MSG_START = "<<PLUGIN_MSG_START>>"
        MSG_END = "<<PLUGIN_MSG_END>>"

        def __init__(self):
            self.plugin_id = os.environ.get("PLUGIN_ID", "unknown")
            self.plugin_dir = os.environ.get("PLUGIN_DIR", "unknown")

        def handler(self, method: str):
            """方法处理器装饰器（注册到闭包中的 _handlers）"""
            def decorator(func: Callable):
                _handlers[method] = func  # 使用闭包中的 _handlers
                return func
            return decorator

        def register(self, method: str, func: Callable):
            """注册方法处理器"""
            _handlers[method] = func  # 使用闭包中的 _handlers

        def send_response(self, msg_id: int, result: Any = None, error: str = None):
            """发送响应到 Tauri"""
            response = {"id": msg_id}
            if error:
                response["error"] = error
            else:
                response["result"] = result
            print(f"{self.MSG_START}{json.dumps(response, ensure_ascii=False)}{self.MSG_END}", flush=True)

        def send_event(self, event_name: str, data: Any = None):
            """发送事件到插件前端"""
            response = {
                "id": 0,
                "result": {"event": event_name, "data": data}
            }
            print(f"{self.MSG_START}{json.dumps(response, ensure_ascii=False)}{self.MSG_END}", flush=True)

        def logerr(self, message: str):
            """输出日志到 stderr"""
            sys.stderr.write(f"{message}\n")
            sys.stderr.flush()
        def loginfo(self,message: str):
            print(f"{message}",flush=True)

        def run(self):
            """启动主循环（handlers 和验证逻辑都在闭包中，无法被绕过）"""
            """后端就绪事件通知"""

            self.send_event("__backend_ready__", {"status": "ready"})
            stdin = open(sys.stdin.fileno(), encoding="utf-8", errors="replace", closefd=False)
            for line in stdin:
                msg_id = 0
                try:
                    msg = json.loads(line.strip())
                    msg_id = msg.get("id", 0)
                    method = msg.get("method", "")
                    params = msg.get("params", {})
                    token = msg.get("token")

                    # 使用闭包中的验证函数
                    if not _internal_verify(msg_id, method, params, token):
                        self.send_response(msg_id, error="Token 验证失败")
                        continue

                    # 使用闭包中的 _handlers
                    if method in _handlers:
                        result = _handlers[method](params)
                        self.send_response(msg_id, result=result)
                    else:
                        self.send_response(msg_id, error=f"Unknown method: {method}")

                except json.JSONDecodeError as e:
                    self.logerr(f"JSON parse error: {e}")
                except Exception as e:
                    self.send_response(msg_id, error=str(e))

    return _PluginSDK()


# 创建全局 SDK 实例（验证逻辑已封装在闭包中）
sdk = _create_sdk_with_protected_verifier()
