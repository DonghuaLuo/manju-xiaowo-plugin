#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小蜗工具 - 插件后端 SDK
封装stdin/stdout JSON-RPC 安全通信协议

默认运行模型接近 FastAPI：
- 主循环只负责持续读取 stdin、鉴权和投递请求。
- 普通同步 handler 在线程池执行，async handler 在 SDK 事件循环执行。
- 响应通过独立写队列回传，避免慢 handler 或 pipe ack 阻塞后续请求读取。
"""

import sys
import json
import os
import base64
import asyncio
import inspect
import threading
import queue
import time
import traceback
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from typing import Callable, Dict, Any, Optional

# Ed25519 签名验证
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


_PROTOCOL_STDIN = None
_PROTOCOL_STDOUT = None
_PROTOCOL_WRITE_LOCK = threading.Lock()
_ISOLATED_STDIN_REF = None
_PROTOCOL_PIPE_VERSION = "2026-05-23"
_PROTOCOL_PIPE_ENV = "XIAOWO_PLUGIN_PROTOCOL_PIPE"
_PROTOCOL_PIPE_START_ID_ENV = "XIAOWO_PLUGIN_PROTOCOL_START_ID"
_PROTOCOL_PIPE_TOKEN_ENV = "XIAOWO_PLUGIN_PROTOCOL_TOKEN"
_PROTOCOL_PIPE_VERSION_ENV = "XIAOWO_PLUGIN_PROTOCOL_VERSION"
_PROTOCOL_PIPE_ACK_TIMEOUT_SECONDS = 10.0
_PROTOCOL_PIPE_ACK_MIN_BYTES_PER_SECOND = 2 * 1024 * 1024
_PROTOCOL_PIPE_RETRY_DELAY_SECONDS = 0.05
_SDK_CONCURRENT_ENV = "XIAOWO_PLUGIN_SDK_CONCURRENT"
_SDK_MAX_WORKERS_ENV = "XIAOWO_PLUGIN_SDK_MAX_WORKERS"
_SDK_DRAIN_TIMEOUT_ENV = "XIAOWO_PLUGIN_SDK_DRAIN_TIMEOUT_SECONDS"
_SDK_DEFAULT_DRAIN_TIMEOUT_SECONDS = 30.0


def _protocol_pipe_ack_timeout_for_size(byte_count: int) -> float:
    return max(
        _PROTOCOL_PIPE_ACK_TIMEOUT_SECONDS,
        byte_count / _PROTOCOL_PIPE_ACK_MIN_BYTES_PER_SECOND,
    )


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _read_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


class _LockedStdoutWrapper:
    """让 Python 级 stdout 写入与协议 stdout 写入共用同一把锁。"""

    def __init__(self, wrapped, lock):
        self._wrapped = wrapped
        self._lock = lock

    def write(self, data):
        with self._lock:
            return self._wrapped.write(data)

    def writelines(self, lines):
        with self._lock:
            return self._wrapped.writelines(lines)

    def flush(self):
        with self._lock:
            return self._wrapped.flush()

    def reconfigure(self, *args, **kwargs):
        with self._lock:
            return self._wrapped.reconfigure(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _setup_protocol_stdio():
    """隔离协议 stdin，避免后台线程里的子进程继承 Tauri JSON-RPC 输入管道。"""
    global _PROTOCOL_STDIN, _PROTOCOL_STDOUT, _ISOLATED_STDIN_REF
    if _PROTOCOL_STDIN is not None and _PROTOCOL_STDOUT is not None:
        return

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    original_stdin = sys.stdin
    original_stdin_fd = os.dup(sys.stdin.fileno())
    original_stdout_fd = os.dup(sys.stdout.fileno())

    _PROTOCOL_STDIN = open(
        original_stdin_fd,
        "r",
        encoding="utf-8",
        errors="replace",
        closefd=True,
    )
    _PROTOCOL_STDOUT = open(
        original_stdout_fd,
        "w",
        encoding="utf-8",
        errors="replace",
        closefd=True,
        buffering=1,
    )

    devnull_read_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(devnull_read_fd, sys.stdin.fileno())
    finally:
        os.close(devnull_read_fd)

    # 保留原 stdin 对象引用，避免对象析构时关闭已重定向到 NUL 的 fd0。
    _ISOLATED_STDIN_REF = original_stdin
    sys.stdin = open(
        sys.stdin.fileno(),
        "r",
        encoding="utf-8",
        errors="replace",
        closefd=False,
    )
    sys.stdout = _LockedStdoutWrapper(sys.stdout, _PROTOCOL_WRITE_LOCK)


_setup_protocol_stdio()


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
            self._handler_options = {}
            self._protocol_pipe_path = os.environ.get(_PROTOCOL_PIPE_ENV, "").strip()
            self._protocol_start_id = os.environ.get(_PROTOCOL_PIPE_START_ID_ENV, "0").strip()
            self._protocol_token = os.environ.get(_PROTOCOL_PIPE_TOKEN_ENV, "").strip()
            self._protocol_version = os.environ.get(
                _PROTOCOL_PIPE_VERSION_ENV,
                _PROTOCOL_PIPE_VERSION,
            ).strip()
            self._protocol_pipe_fd = None
            self._protocol_read_buffer = b""
            self._protocol_seq = 0
            self._protocol_pipe_disabled = not (
                self._protocol_pipe_path
                and self._protocol_start_id
                and self._protocol_token
                and self._protocol_version == _PROTOCOL_PIPE_VERSION
            )
            self._protocol_outbox = queue.Queue()
            self._protocol_writer_thread = threading.Thread(
                target=self._protocol_writer_worker,
                name="xiaowo-protocol-writer",
                daemon=True,
            )
            self._protocol_writer_thread.start()

            default_workers = min(32, (os.cpu_count() or 1) + 4)
            self._concurrent_default = _read_bool_env(_SDK_CONCURRENT_ENV, True)
            self._max_workers = _read_int_env(_SDK_MAX_WORKERS_ENV, default_workers)
            self._drain_timeout_seconds = _read_float_env(
                _SDK_DRAIN_TIMEOUT_ENV,
                _SDK_DEFAULT_DRAIN_TIMEOUT_SECONDS,
            )
            self._executor = None
            self._executor_lock = threading.Lock()
            self._runtime_loop = None
            self._runtime_loop_thread = None
            self._runtime_loop_ready_event = None
            self._runtime_loop_lock = threading.Lock()
            self._pending_futures = set()
            self._pending_futures_lock = threading.Lock()

        def _log_stdout_fallback_locked(self, reason: str):
            try:
                _PROTOCOL_STDOUT.write(f"退回为stdout: {reason}\n")
                _PROTOCOL_STDOUT.flush()
            except Exception:
                pass

        def _open_protocol_pipe_fd_locked(self) -> int:
            flags = os.O_RDWR
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            return os.open(self._protocol_pipe_path, flags)

        def _close_protocol_pipe_locked(self):
            fd = self._protocol_pipe_fd
            self._protocol_pipe_fd = None
            self._protocol_read_buffer = b""
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass

        def _read_protocol_pipe_chunk_locked(self, timeout_seconds: float) -> bytes:
            fd = self._protocol_pipe_fd
            if fd is None:
                raise RuntimeError("插件协议 pipe 未连接")

            result_queue = queue.Queue(maxsize=1)

            def read_once():
                try:
                    result_queue.put(("ok", os.read(fd, 4096)))
                except Exception as exc:
                    result_queue.put(("error", exc))

            reader = threading.Thread(
                target=read_once,
                name="xiaowo-protocol-ack-read-once",
                daemon=True,
            )
            reader.start()
            try:
                status, value = result_queue.get(timeout=timeout_seconds)
            except queue.Empty:
                raise TimeoutError("等待插件协议 pipe 数据超时")

            if status == "error":
                raise RuntimeError(str(value))
            if not value:
                raise RuntimeError("插件协议 pipe 已关闭")
            return value

        def _write_protocol_pipe_bytes_locked(self, data: bytes):
            if self._protocol_pipe_fd is None:
                raise RuntimeError("插件协议 pipe 未连接")
            view = memoryview(data)
            offset = 0
            while offset < len(view):
                written = os.write(self._protocol_pipe_fd, view[offset:])
                if written <= 0:
                    raise RuntimeError("插件协议 pipe 写入返回 0")
                offset += written

        def _write_protocol_pipe_frame_locked(self, frame: Dict[str, Any]):
            data = (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
            self._write_protocol_pipe_bytes_locked(data)
            return len(data)

        def _wait_protocol_pipe_ack_locked(self, seq: int, timeout_seconds: float):
            if self._protocol_pipe_fd is None:
                raise RuntimeError("插件协议 pipe 未连接")
            deadline = time.monotonic() + timeout_seconds
            while True:
                while b"\n" in self._protocol_read_buffer:
                    line, self._protocol_read_buffer = self._protocol_read_buffer.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        ack = json.loads(text)
                    except Exception as exc:
                        raise RuntimeError(f"解析插件协议 ack 失败: {exc}") from exc

                    if ack.get("type") == "error":
                        raise RuntimeError(str(ack.get("error") or "插件协议 ack 读取失败"))

                    if ack.get("type") != "ack":
                        continue

                    try:
                        ack_seq = int(ack.get("seq", -1))
                    except (TypeError, ValueError):
                        continue

                    if ack_seq != seq:
                        continue

                    if ack.get("ok") is True:
                        return

                    raise RuntimeError(str(ack.get("error") or "插件协议 ack 失败"))

                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    raise TimeoutError(f"等待插件协议 ack 超时: seq={seq}")
                self._protocol_read_buffer += self._read_protocol_pipe_chunk_locked(timeout)

        def _connect_protocol_pipe_once_locked(self):
            start_id = int(self._protocol_start_id)
            fd = self._open_protocol_pipe_fd_locked()
            self._protocol_pipe_fd = fd
            self._protocol_read_buffer = b""

            hello = {
                "type": "hello",
                "seq": 0,
                "plugin_id": self.plugin_id,
                "start_id": start_id,
                "token": self._protocol_token,
                "protocol_version": self._protocol_version,
            }
            frame_size = self._write_protocol_pipe_frame_locked(hello)
            self._wait_protocol_pipe_ack_locked(0, _protocol_pipe_ack_timeout_for_size(frame_size))

        def _connect_protocol_pipe_locked(self) -> bool:
            if self._protocol_pipe_disabled:
                return False
            if self._protocol_pipe_fd is not None:
                return True

            last_error = None
            for attempt in range(2):
                try:
                    self._connect_protocol_pipe_once_locked()
                    return True
                except Exception as exc:
                    last_error = exc
                    self._close_protocol_pipe_locked()
                    if attempt == 0:
                        time.sleep(_PROTOCOL_PIPE_RETRY_DELAY_SECONDS)

            self._protocol_pipe_disabled = True
            self._log_stdout_fallback_locked(
                f"插件协议 pipe 不可用: {last_error}"
            )
            return False

        def _send_protocol_pipe_message_locked(self, payload: Dict[str, Any]) -> bool:
            self._protocol_seq += 1
            seq = self._protocol_seq
            frame = {
                "type": "message",
                "seq": seq,
                "payload": payload,
            }

            last_error = None
            for attempt in range(2):
                if not self._connect_protocol_pipe_locked():
                    return False
                try:
                    frame_size = self._write_protocol_pipe_frame_locked(frame)
                    self._wait_protocol_pipe_ack_locked(seq, _protocol_pipe_ack_timeout_for_size(frame_size))
                    return True
                except Exception as exc:
                    last_error = exc
                    self._close_protocol_pipe_locked()
                    if attempt == 0:
                        time.sleep(_PROTOCOL_PIPE_RETRY_DELAY_SECONDS)

            self._protocol_pipe_disabled = True
            self._log_stdout_fallback_locked(
                f"插件协议 pipe 发送失败: {last_error}"
            )
            return False

        def _disable_protocol_pipe_locked(self, reason: str):
            if not self._protocol_pipe_disabled:
                self._protocol_pipe_disabled = True
                self._close_protocol_pipe_locked()
                self._log_stdout_fallback_locked(reason)

        def _write_stdout_protocol_locked(self, payload: Dict[str, Any]):
            message = f"{self.MSG_START}{json.dumps(payload, ensure_ascii=False)}{self.MSG_END}\n"
            _PROTOCOL_STDOUT.write(message)
            _PROTOCOL_STDOUT.flush()

        def _send_protocol_message(self, payload: Dict[str, Any]):
            with _PROTOCOL_WRITE_LOCK:
                if self._send_protocol_pipe_message_locked(payload):
                    return

                self._write_stdout_protocol_locked(payload)

        def _protocol_writer_worker(self):
            while True:
                payload = self._protocol_outbox.get()
                try:
                    if payload is None:
                        return
                    self._send_protocol_message(payload)
                except Exception:
                    self.logerr(traceback.format_exc())
                finally:
                    self._protocol_outbox.task_done()

        def _enqueue_protocol_message(self, payload: Dict[str, Any]):
            self._protocol_outbox.put(payload)

        def _ensure_executor(self) -> ThreadPoolExecutor:
            with self._executor_lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix="xiaowo-handler",
                    )
                return self._executor

        def _runtime_loop_worker(self, ready_event: threading.Event):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._runtime_loop_lock:
                self._runtime_loop = loop
            ready_event.set()
            try:
                loop.run_forever()
            finally:
                pending_tasks = asyncio.all_tasks(loop)
                for task in pending_tasks:
                    task.cancel()
                if pending_tasks:
                    loop.run_until_complete(
                        asyncio.gather(*pending_tasks, return_exceptions=True)
                    )
                loop.close()

        def _ensure_runtime_loop(self) -> asyncio.AbstractEventLoop:
            with self._runtime_loop_lock:
                if self._runtime_loop is not None and self._runtime_loop.is_running():
                    return self._runtime_loop

                if (
                    self._runtime_loop_ready_event is None
                    or self._runtime_loop_thread is None
                    or not self._runtime_loop_thread.is_alive()
                ):
                    self._runtime_loop_ready_event = threading.Event()
                    self._runtime_loop_thread = threading.Thread(
                        target=self._runtime_loop_worker,
                        args=(self._runtime_loop_ready_event,),
                        name="xiaowo-runtime-loop",
                        daemon=True,
                    )
                    self._runtime_loop_thread.start()

                ready_event = self._runtime_loop_ready_event

            ready_event.wait()
            with self._runtime_loop_lock:
                if self._runtime_loop is None:
                    raise RuntimeError("小蜗 SDK 异步事件循环启动失败")
                return self._runtime_loop

        async def _invoke_handler_async(self, handler_func: Callable, params: Any):
            if inspect.iscoroutinefunction(handler_func):
                return await handler_func(params)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._ensure_executor(),
                handler_func,
                params,
            )
            if inspect.isawaitable(result):
                return await result
            return result

        def _invoke_handler_blocking(self, handler_func: Callable, params: Any):
            if inspect.iscoroutinefunction(handler_func):
                future = asyncio.run_coroutine_threadsafe(
                    handler_func(params),
                    self._ensure_runtime_loop(),
                )
                return future.result()

            result = handler_func(params)
            if inspect.isawaitable(result):
                future = asyncio.run_coroutine_threadsafe(
                    result,
                    self._ensure_runtime_loop(),
                )
                return future.result()
            return result

        def _track_future(self, future: Future):
            with self._pending_futures_lock:
                self._pending_futures.add(future)

        def _untrack_future(self, future: Future):
            with self._pending_futures_lock:
                self._pending_futures.discard(future)

        def _should_run_concurrently(self, method: str) -> bool:
            option = self._handler_options.get(method, {}).get("concurrent")
            if option is None:
                return self._concurrent_default
            return bool(option)

        def _finish_handler_future(self, msg_id: int, future: Future):
            try:
                if future.cancelled():
                    self.send_response(msg_id, error="请求已取消")
                    return
                result = future.result()
                self.send_response(msg_id, result=result)
            except CancelledError:
                self.send_response(msg_id, error="请求已取消")
            except Exception as exc:
                self.logerr(traceback.format_exc())
                self.send_response(msg_id, error=str(exc))
            finally:
                self._untrack_future(future)

        def _submit_handler(self, msg_id: int, method: str, params: Any):
            handler_func = _handlers.get(method)
            if handler_func is None:
                self.send_response(msg_id, error=f"Unknown method: {method}")
                return

            if not self._should_run_concurrently(method):
                try:
                    result = self._invoke_handler_blocking(handler_func, params)
                    self.send_response(msg_id, result=result)
                except Exception as exc:
                    self.logerr(traceback.format_exc())
                    self.send_response(msg_id, error=str(exc))
                return

            future = asyncio.run_coroutine_threadsafe(
                self._invoke_handler_async(handler_func, params),
                self._ensure_runtime_loop(),
            )
            self._track_future(future)
            future.add_done_callback(
                lambda completed_future, response_id=msg_id: self._finish_handler_future(
                    response_id,
                    completed_future,
                )
            )

        def _drain_pending_futures(self):
            deadline = time.monotonic() + self._drain_timeout_seconds
            while True:
                with self._pending_futures_lock:
                    pending = list(self._pending_futures)
                if not pending:
                    return

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    for future in pending:
                        future.cancel()
                    cancel_deadline = time.monotonic() + 1.0
                    while time.monotonic() < cancel_deadline:
                        with self._pending_futures_lock:
                            if not self._pending_futures:
                                return
                        time.sleep(0.02)
                    return
                time.sleep(min(0.05, remaining))

        def _shutdown_runtime(self):
            self._drain_pending_futures()
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._executor.shutdown(wait=False)
            with self._runtime_loop_lock:
                loop = self._runtime_loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)

        def handler(self, method: str, *, concurrent: Optional[bool] = None):
            """方法处理器装饰器（注册到闭包中的 _handlers）"""
            def decorator(func: Callable):
                _handlers[method] = func  # 使用闭包中的 _handlers
                self._handler_options[method] = {"concurrent": concurrent}
                return func
            return decorator

        def register(
            self,
            method: str,
            func: Callable,
            *,
            concurrent: Optional[bool] = None,
        ):
            """注册方法处理器"""
            _handlers[method] = func  # 使用闭包中的 _handlers
            self._handler_options[method] = {"concurrent": concurrent}
            return func

        def send_response(self, msg_id: int, result: Any = None, error: str = None):
            """发送响应到 Tauri"""
            response = {"id": msg_id}
            if error:
                response["error"] = error
            else:
                response["result"] = result
            self._enqueue_protocol_message(response)

        def send_event(self, event_name: str, data: Any = None):
            """发送事件到插件前端"""
            response = {
                "id": 0,
                "result": {"event": event_name, "data": data}
            }
            self._enqueue_protocol_message(response)

        def logerr(self, message: str):
            """输出日志到 stderr"""
            sys.stderr.write(f"{message}\n")
            sys.stderr.flush()
        def loginfo(self,message: str):
            print(f"{message}", flush=True)

        def run(self, *, concurrent: Optional[bool] = None):
            """启动主循环（handlers 和验证逻辑都在闭包中，无法被绕过）"""
            """后端就绪事件通知"""
            if concurrent is not None:
                self._concurrent_default = bool(concurrent)

            try:
                self.send_event("__backend_ready__", {"status": "ready"})
                for line in _PROTOCOL_STDIN:
                    msg_id = 0
                    try:
                        text = line.strip()
                        if not text:
                            continue

                        msg = json.loads(text)
                        msg_id = msg.get("id", 0)
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        token = msg.get("token")

                        # 使用闭包中的验证函数
                        if not _internal_verify(msg_id, method, params, token):
                            self.send_response(msg_id, error="Token 验证失败")
                            continue

                        self._submit_handler(msg_id, method, params)

                    except json.JSONDecodeError as e:
                        self.logerr(f"JSON parse error: {e}")
                    except Exception as e:
                        self.logerr(traceback.format_exc())
                        self.send_response(msg_id, error=str(e))
            finally:
                self._shutdown_runtime()
                self._protocol_outbox.join()

    return _PluginSDK()


# 创建全局 SDK 实例（验证逻辑已封装在闭包中）
sdk = _create_sdk_with_protected_verifier()
