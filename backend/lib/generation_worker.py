"""
Background worker that consumes generation tasks from SQLite queue.

Per-provider pool scheduling: each provider gets independent concurrency
limits for image and video tasks, read from ConfigService (DB).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from datetime import UTC

# Lease 丢失超过 ``lease_ttl * _ORPHAN_RESCAN_LEASE_LOST_MULT`` 才认为是真切换 owner
# （另一个 worker 进程曾持过 lease 且写入了新 orphan），需要重扫；短 flap 不触发。
_ORPHAN_RESCAN_LEASE_LOST_MULT = 3
_ORPHAN_RESUME_CAPACITY_POLL_SEC = 0.5

from lib.generation_queue import (
    TASK_POLL_INTERVAL_SEC,
    TASK_WORKER_HEARTBEAT_SEC,
    TASK_WORKER_LEASE_TTL_SEC,
    GenerationQueue,
    _derive_image_capability_for_task,
    get_generation_queue,
)

# Default provider used when a task payload does not specify one.
DEFAULT_PROVIDER = "gemini-aistudio"


def _non_resumable_video_providers() -> frozenset[str]:
    """不实现 VideoBackend.resume_video 的视频 provider 集合。"""
    from lib.providers import PROVIDER_GROK, PROVIDER_VIDU

    return frozenset({PROVIDER_GROK, PROVIDER_VIDU})


NON_RESUMABLE_VIDEO_PROVIDERS = _non_resumable_video_providers()


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


@dataclass
class ProviderPool:
    """Per-provider concurrency pool with independent image/video lanes."""

    provider_id: str
    image_max: int  # 0 = this provider doesn't support image
    video_max: int  # 0 = this provider doesn't support video
    image_inflight: dict[str, asyncio.Task] = field(default_factory=dict)
    video_inflight: dict[str, asyncio.Task] = field(default_factory=dict)
    video_pending: dict[str, asyncio.Task] = field(default_factory=dict)

    def has_image_room(self) -> bool:
        return self.image_max > 0 and len(self.image_inflight) < self.image_max

    def has_video_room(self) -> bool:
        return self.video_max > 0 and len(self.video_inflight) + len(self.video_pending) < self.video_max

    def drain_finished(self) -> list[tuple[str, asyncio.Task]]:
        """Remove finished tasks from inflight dicts. Return task_id + task for await."""
        finished = []
        for inflight in (self.image_inflight, self.video_inflight):
            done_ids = [tid for tid, t in inflight.items() if t.done()]
            for tid in done_ids:
                finished.append((tid, inflight.pop(tid)))
        return finished

    def all_inflight(self) -> list[asyncio.Task]:
        return [*self.image_inflight.values(), *self.video_inflight.values()]

    def all_active(self) -> list[asyncio.Task]:
        return [*self.image_inflight.values(), *self.video_inflight.values(), *self.video_pending.values()]


async def _extract_provider(task: dict[str, Any]) -> str:
    """Extract provider_id from a claimed task, used only for rate-limit pool routing."""
    project_name = task.get("project_name")
    payload = task.get("payload") or {}
    is_video = task.get("media_type") == "video" or task.get("task_type") in ("video", "reference_video")

    try:
        project: dict | None = None
        if project_name:
            from lib.config.resolver import get_project_manager

            project = await asyncio.to_thread(get_project_manager().load_project, project_name)

        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        resolver = ConfigResolver(async_session_factory)
        if is_video:
            resolved = await resolver.resolve_video_backend(project, payload)
        else:
            capability = await asyncio.to_thread(
                _derive_image_capability_for_task,
                project_name=project_name,
                project=project,
                payload=payload,
                task_type=task.get("task_type") or "",
                resource_id=str(task.get("resource_id") or "") or None,
                script_file=task.get("script_file") or payload.get("script_file"),
            )
            resolved = await resolver.resolve_image_backend(project, payload, capability=capability)
    except Exception:
        logger.debug("provider 解析失败，回退 DEFAULT_PROVIDER 仅供限流路由", exc_info=True)
        return DEFAULT_PROVIDER
    return resolved.provider_id or DEFAULT_PROVIDER


async def _load_pools_from_db() -> dict[str, ProviderPool]:
    """Load per-provider pool configs from ConfigService + PROVIDER_REGISTRY + custom providers."""
    from lib.config.registry import PROVIDER_REGISTRY
    from lib.config.service import ConfigService
    from lib.db import safe_session_factory
    from lib.db.repositories.custom_provider_repo import CustomProviderRepository

    default_image = _read_int_env("IMAGE_MAX_WORKERS", 5, minimum=1)
    default_video = _read_int_env("VIDEO_MAX_WORKERS", 3, minimum=1)

    pools: dict[str, ProviderPool] = {}
    async with safe_session_factory() as session:
        svc = ConfigService(session)
        all_configs = await svc.get_all_provider_configs()
        for provider_id, meta in PROVIDER_REGISTRY.items():
            config = all_configs.get(provider_id, {})
            supports_image = "image" in meta.media_types
            supports_video = "video" in meta.media_types
            image_max = int(config.get("image_max_workers", str(default_image))) if supports_image else 0
            video_max = int(config.get("video_max_workers", str(default_video))) if supports_video else 0
            pools[provider_id] = ProviderPool(
                provider_id=provider_id,
                image_max=max(0, image_max),
                video_max=max(0, video_max),
            )

        # 加载自定义供应商的池配置（使用与内置供应商相同的默认值）
        from lib.custom_provider.endpoints import endpoint_to_media_type

        repo = CustomProviderRepository(session)
        for provider, models in await repo.list_providers_with_models():
            pid = provider.provider_id  # "custom-{id}"
            media_types = {endpoint_to_media_type(m.endpoint) for m in models if m.is_enabled}
            pools[pid] = ProviderPool(
                provider_id=pid,
                image_max=default_image if "image" in media_types else 0,
                video_max=default_video if "video" in media_types else 0,
            )

    logger.info(
        "从 DB 加载供应商池配置: %s",
        {pid: (p.image_max, p.video_max) for pid, p in pools.items()},
    )
    return pools


def _build_default_pools() -> dict[str, ProviderPool]:
    """Build pools from env vars / defaults (used before DB is available or in tests).

    为 PROVIDER_REGISTRY 中所有供应商创建默认池，避免 DB 加载前的任务
    因供应商未知而降级到 1 并发的 fallback 池。
    """
    from lib.config.registry import PROVIDER_REGISTRY

    image_max = _read_int_env("IMAGE_MAX_WORKERS", 5, minimum=1)
    video_max = _read_int_env("VIDEO_MAX_WORKERS", 3, minimum=1)

    pools: dict[str, ProviderPool] = {}
    for provider_id, meta in PROVIDER_REGISTRY.items():
        pools[provider_id] = ProviderPool(
            provider_id=provider_id,
            image_max=image_max if "image" in meta.media_types else 0,
            video_max=video_max if "video" in meta.media_types else 0,
        )
    return pools


class GenerationWorker:
    """Queue worker with per-provider image/video lanes and single-active lease."""

    def __init__(
        self,
        queue: GenerationQueue | None = None,
        lease_name: str = "default",
        pools: dict[str, ProviderPool] | None = None,
    ):
        self.queue = queue or get_generation_queue()
        self.lease_name = lease_name
        self.owner_id = f"worker-{uuid.uuid4().hex[:10]}"

        self._pools: dict[str, ProviderPool] = pools or _build_default_pools()
        logger.info(
            "Worker 初始池配置: %s",
            {pid: (p.image_max, p.video_max) for pid, p in self._pools.items()},
        )
        self.lease_ttl = max(1.0, float(TASK_WORKER_LEASE_TTL_SEC))
        self.heartbeat_interval = max(0.5, float(TASK_WORKER_HEARTBEAT_SEC))
        self.poll_interval = max(0.1, float(TASK_POLL_INTERVAL_SEC))

        self._main_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._owns_lease = False
        self._orphan_dispatcher_task: asyncio.Task | None = None
        self._orphan_handled_once = False
        self._lease_lost_monotonic: float | None = None

    # ------------------------------------------------------------------
    # Backward compatibility shims
    # ------------------------------------------------------------------

    @property
    def image_workers(self) -> int:
        """Total image concurrency across all providers."""
        return sum(p.image_max for p in self._pools.values())

    @property
    def video_workers(self) -> int:
        """Total video concurrency across all providers."""
        return sum(p.video_max for p in self._pools.values())

    @property
    def _image_inflight(self) -> dict[str, asyncio.Task]:
        """Merged view of all image inflight tasks (read-only convenience)."""
        merged: dict[str, asyncio.Task] = {}
        for pool in self._pools.values():
            merged.update(pool.image_inflight)
        return merged

    @property
    def _video_inflight(self) -> dict[str, asyncio.Task]:
        """Merged view of all video inflight tasks (read-only convenience)."""
        merged: dict[str, asyncio.Task] = {}
        for pool in self._pools.values():
            merged.update(pool.video_inflight)
        return merged

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def _get_or_create_pool(self, provider_id: str) -> ProviderPool:
        """Get pool for provider, creating a fallback pool if unknown."""
        pool = self._pools.get(provider_id)
        if pool is not None:
            return pool
        # Unknown provider — use same defaults as built-in providers
        image_max = _read_int_env("IMAGE_MAX_WORKERS", 5, minimum=1)
        video_max = _read_int_env("VIDEO_MAX_WORKERS", 3, minimum=1)
        pool = ProviderPool(
            provider_id=provider_id,
            image_max=image_max,
            video_max=video_max,
        )
        self._pools[provider_id] = pool
        logger.info("为供应商 %s 创建默认池 (image=%d, video=%d)", provider_id, image_max, video_max)
        return pool

    def _any_pool_has_room(self, media_type: str) -> bool:
        """Check if any provider pool has room for the given media_type."""
        for pool in self._pools.values():
            if media_type == "image" and pool.has_image_room():
                return True
            if media_type == "video" and pool.has_video_room():
                return True
        return False

    async def reload_limits(self) -> None:
        """Reload per-provider concurrency limits from DB.

        Preserves in-flight tasks: only updates max limits on existing pools
        and adds/removes pool entries as needed.
        """
        try:
            new_pools = await _load_pools_from_db()
        except Exception:
            logger.warning("从 DB 加载供应商配置失败，保持当前配置", exc_info=True)
            return

        # Migrate inflight + pending tasks to new pool objects.
        for pid, new_pool in new_pools.items():
            old_pool = self._pools.get(pid)
            if old_pool:
                new_pool.image_inflight = old_pool.image_inflight
                new_pool.video_inflight = old_pool.video_inflight
                new_pool.video_pending = old_pool.video_pending

        # Pools that existed before but are no longer registered:
        # keep them alive until their active tasks drain.
        for pid, old_pool in self._pools.items():
            if pid not in new_pools and old_pool.all_active():
                new_pools[pid] = old_pool
                new_pools[pid].image_max = 0
                new_pools[pid].video_max = 0

        self._pools = new_pools
        logger.info(
            "已更新供应商池配置: %s",
            {pid: (p.image_max, p.video_max) for pid, p in self._pools.items()},
        )

    def reload_limits_from_env(self) -> None:
        """Reload worker concurrency limits from environment variables.

        Backward-compatible shim. Prefer reload_limits() for DB-backed config.
        """
        image_max = _read_int_env("IMAGE_MAX_WORKERS", 3, minimum=1)
        video_max = _read_int_env("VIDEO_MAX_WORKERS", 2, minimum=1)
        default_pool = self._pools.get(DEFAULT_PROVIDER)
        if default_pool:
            default_pool.image_max = image_max
            default_pool.video_max = video_max
        else:
            self._pools[DEFAULT_PROVIDER] = ProviderPool(
                provider_id=DEFAULT_PROVIDER,
                image_max=image_max,
                video_max=video_max,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._main_task and not self._main_task.done():
            return
        self._stop_event.clear()
        self._main_task = asyncio.create_task(self._run_loop(), name="generation-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._main_task:
            await self._main_task
            self._main_task = None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                had_lease = self._owns_lease
                self._owns_lease = await self.queue.acquire_or_renew_worker_lease(
                    name=self.lease_name,
                    owner_id=self.owner_id,
                    ttl_seconds=self.lease_ttl,
                )

                if self._owns_lease and not had_lease:
                    logger.info("获得 worker lease (owner=%s)", self.owner_id)
                if had_lease and not self._owns_lease:
                    logger.warning("失去 worker lease (owner=%s)", self.owner_id)

                await self._drain_finished_tasks()

                if had_lease and not self._owns_lease and self._lease_lost_monotonic is None:
                    self._lease_lost_monotonic = time.monotonic()
                if self._owns_lease and self._lease_lost_monotonic is not None:
                    lost_duration = time.monotonic() - self._lease_lost_monotonic
                    if lost_duration > self.lease_ttl * _ORPHAN_RESCAN_LEASE_LOST_MULT:
                        logger.info(
                            "lease 丢失 %.1fs（> %d×ttl=%.1fs），认为另一进程曾持过 lease，重扫 orphan",
                            lost_duration,
                            _ORPHAN_RESCAN_LEASE_LOST_MULT,
                            self.lease_ttl * _ORPHAN_RESCAN_LEASE_LOST_MULT,
                        )
                        self._orphan_handled_once = False
                    self._lease_lost_monotonic = None

                if self._owns_lease and not self._orphan_handled_once:
                    await self._handle_orphan_tasks_on_start()
                    self._orphan_handled_once = True

                if not self._owns_lease:
                    await asyncio.sleep(self.heartbeat_interval)
                    continue

                claimed_any = await self._claim_tasks()

                if claimed_any:
                    await asyncio.sleep(0.05)
                else:
                    await asyncio.sleep(self.poll_interval)

            await self._wait_inflight_completion()
        finally:
            if self._owns_lease:
                await self.queue.release_worker_lease(name=self.lease_name, owner_id=self.owner_id)
            self._owns_lease = False

    def _pool_full_providers(self, media_type: str) -> frozenset[str]:
        """返回当前 cycle 指定 media_type 池已满的 provider_id 集合。"""
        if media_type == "image":
            return frozenset(pid for pid, p in self._pools.items() if p.image_max > 0 and not p.has_image_room())
        return frozenset(pid for pid, p in self._pools.items() if p.video_max > 0 and not p.has_video_room())

    async def _claim_tasks(self) -> bool:
        """Claim tasks from queue and route to per-provider pools.

        池满 task 在 SQL 层按 provider 黑名单过滤，避免 claim → requeue 反复刷屏。
        """
        claimed_any = False

        for media_type in ("image", "video"):
            while True:
                pool_full = self._pool_full_providers(media_type)
                task = await self.queue.claim_next_task(
                    media_type=media_type,
                    pool_full_providers=pool_full,
                )
                if not task:
                    break

                provider_id = await _extract_provider(task)
                pool = self._get_or_create_pool(provider_id)

                if media_type == "image":
                    max_capacity = pool.image_max
                    has_room = pool.has_image_room()
                else:
                    max_capacity = pool.video_max
                    has_room = pool.has_video_room()

                if max_capacity == 0:
                    # 供应商不支持此媒体类型（容量为 0），直接失败
                    logger.warning(
                        "供应商 %s 不支持 %s 生成，任务 %s 标记失败",
                        provider_id,
                        media_type,
                        task["task_id"],
                    )
                    await self.queue.mark_task_failed(
                        task["task_id"],
                        f"供应商 {provider_id} 不支持 {media_type} 生成",
                    )
                    claimed_any = True
                    continue

                if not has_room:
                    logger.info(
                        "供应商 %s 的 %s 池满，task %s 回队等待下一 cycle",
                        provider_id,
                        media_type,
                        task["task_id"],
                    )
                    await self._requeue_single_task(task["task_id"])
                    # 下一轮 SQL 会重算 pool_full 并过滤掉这个 provider。
                    break

                # Dispatch to pool
                claimed_any = True
                inflight = pool.image_inflight if media_type == "image" else pool.video_inflight
                inflight[task["task_id"]] = asyncio.create_task(
                    self._process_task(task),
                    name=f"generation-{media_type}-{task['task_id']}",
                )

        return claimed_any

    async def _requeue_single_task(self, task_id: str) -> None:
        """Put a claimed running task back to queued status."""
        try:
            from datetime import datetime

            from sqlalchemy import update

            from lib.db import safe_session_factory
            from lib.db.models.task import Task

            async with safe_session_factory() as session:
                await session.execute(
                    update(Task)
                    .where(Task.task_id == task_id, Task.status == "running")
                    .values(
                        status="queued",
                        started_at=None,
                        updated_at=datetime.now(UTC),
                    )
                )
                await session.commit()
            logger.debug("回队任务 %s (供应商池已满)", task_id)
        except Exception:
            logger.warning("回队任务 %s 失败", task_id, exc_info=True)

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    async def _drain_finished_tasks(self) -> None:
        for pool in self._pools.values():
            for task_id, finished_task in pool.drain_finished():
                if finished_task.cancelled():
                    try:
                        await self.queue.mark_task_cancelled(task_id, cancelled_by="user")
                    except Exception:
                        logger.warning("drain finished cancelled task 落终态失败: %s", task_id, exc_info=True)
                    continue
                try:
                    finished_task.result()
                except asyncio.CancelledError:
                    logger.debug("已处理的任务取消已在 _process_task 中记录")
                except Exception:
                    logger.debug("已处理的任务异常已在 _process_task 中记录")

    async def _wait_inflight_completion(self) -> None:
        if self._orphan_dispatcher_task is not None and not self._orphan_dispatcher_task.done():
            try:
                await self._orphan_dispatcher_task
            except Exception:
                logger.exception("orphan dispatcher 在 shutdown 等待时异常")

        pending_tasks = []
        for pool in self._pools.values():
            pending_tasks.extend(pool.all_active())
        if not pending_tasks:
            return
        await asyncio.gather(*pending_tasks, return_exceptions=True)
        for pool in self._pools.values():
            pool.image_inflight.clear()
            pool.video_inflight.clear()
            pool.video_pending.clear()

    async def _process_task(self, task: dict[str, Any]) -> None:
        """Run a generation task with 0-rows-cancelled finally protocol."""
        task_id = task["task_id"]
        task_type = task.get("task_type", "unknown")
        provider_id = await _extract_provider(task)
        logger.info("开始处理任务 %s (type=%s, provider=%s)", task_id, task_type, provider_id)

        from server.services.generation_tasks import execute_generation_task

        try:
            result = await execute_generation_task(task)
        except asyncio.CancelledError:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            raise
        except Exception as exc:
            logger.exception("任务失败 %s (type=%s, provider=%s)", task_id, task_type, provider_id)
            from lib.friendly_errors import summarize_generation_error

            rows = await asyncio.shield(
                self.queue.mark_task_failed(
                    task_id,
                    summarize_generation_error(exc, provider_id=provider_id, task=task),
                )
            )
            if rows == 0:
                await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            return

        try:
            rows = await asyncio.shield(self.queue.mark_task_succeeded(task_id, result))
        except asyncio.CancelledError:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            raise
        except Exception:
            logger.exception("标记任务成功失败 %s", task_id)
            raise
        if rows == 0:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
        else:
            logger.info("任务完成 %s (type=%s, provider=%s)", task_id, task_type, provider_id)

    async def _process_resume_task(self, task: dict[str, Any]) -> None:
        """重启自愈入口：直接调 backend.resume_video，绕过 normal executor 流水线。"""
        task_id = task["task_id"]
        task_type = task.get("task_type", "unknown")

        job_id = task.get("provider_job_id") or ""
        if not job_id:
            rows = await asyncio.shield(
                self.queue.mark_task_failed(task_id, "[restart_lost] 无 provider_job_id 但被派发到 resume")
            )
            if rows == 0:
                await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            return

        persisted_provider_id = task.get("provider_id")
        if persisted_provider_id:
            payload = task.get("payload")
            if payload is None:
                payload = {}
                task["payload"] = payload
            is_video = task.get("media_type") == "video" or task_type in ("video", "reference_video")
            if is_video:
                payload["video_provider"] = persisted_provider_id
            else:
                payload["image_provider"] = persisted_provider_id

        provider_id = await _extract_provider(task)
        logger.info("重启自愈处理任务 %s (type=%s, provider=%s, job=%s)", task_id, task_type, provider_id, job_id)

        from lib.video_backends.base import ResumeExpiredError
        from server.services.resume_executor import execute_resume_video_task

        try:
            result = await execute_resume_video_task(task, job_id=job_id)
        except asyncio.CancelledError:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            raise
        except NotImplementedError as exc:
            logger.warning("resume 不支持 task %s: %s", task_id, exc)
            rows = await asyncio.shield(self.queue.mark_task_failed(task_id, f"[resume_unsupported] {exc}"))
            if rows == 0:
                await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            return
        except ResumeExpiredError as exc:
            logger.warning("resume 已过期 task %s: %s", task_id, exc)
            rows = await asyncio.shield(self.queue.mark_task_failed(task_id, f"[resume_expired] {exc}"))
            if rows == 0:
                await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            return
        except Exception as exc:
            logger.exception("resume 失败 %s (type=%s, provider=%s)", task_id, task_type, provider_id)
            rows = await asyncio.shield(self.queue.mark_task_failed(task_id, str(exc)))
            if rows == 0:
                await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            return

        try:
            rows = await asyncio.shield(self.queue.mark_task_succeeded(task_id, result))
        except asyncio.CancelledError:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
            raise
        if rows == 0:
            await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
        else:
            logger.info("重启自愈完成 %s", task_id)

    def request_cancel(self, task_id: str) -> bool:
        """In-process cancel 信号：找到 inflight asyncio.Task 后 cancel。"""
        for pool in self._pools.values():
            for inflight in (pool.image_inflight, pool.video_inflight, pool.video_pending):
                t = inflight.get(task_id)
                if t is not None and not t.done():
                    t.cancel()
                    logger.info("已对 task %s 发出 in-process cancel 信号", task_id)
                    return True
        logger.info("request_cancel: task %s 不在 inflight (worker finally 兜底)", task_id)
        return False

    async def _handle_orphan_tasks_on_start(self) -> None:
        """重启自愈：扫 running + cancelling 孤儿，按是否可安全 resume 分流。"""
        orphans = await self.queue.list_orphan_tasks_on_start()
        if not orphans:
            return
        logger.info(
            "等待 lease 获取后开始扫孤儿（待处理 %d 个）…lease_ttl=%.0fs",
            len(orphans),
            self.lease_ttl,
        )

        self_active_task_ids: set[str] = set()
        for pool in self._pools.values():
            self_active_task_ids.update(pool.image_inflight.keys())
            self_active_task_ids.update(pool.video_inflight.keys())
            self_active_task_ids.update(pool.video_pending.keys())

        resumable_by_provider: dict[str, list[dict[str, Any]]] = {}

        for task in orphans:
            task_id = task["task_id"]
            if task_id in self_active_task_ids:
                logger.info("孤儿扫到本进程仍 active 的 task %s，跳过避免 self-preemption", task_id)
                continue
            status = task.get("status")
            if status == "cancelling":
                await self.queue.mark_task_cancelled(task_id, cancelled_by="user")
                logger.info("孤儿 cancelling → cancelled: %s", task_id)
                continue

            media_type = task.get("media_type") or (
                "video" if task.get("task_type") in ("video", "reference_video") else "image"
            )

            if media_type == "image":
                logger.warning("孤儿 image running → [restart_lost]: %s", task_id)
                rows = await self.queue.mark_task_failed(
                    task_id,
                    "[restart_lost] image 任务无法接续，需手动重试以避免重复计费",
                )
                if rows == 0:
                    await self.queue.mark_task_cancelled(task_id, cancelled_by="user")
                continue

            provider_id = task.get("provider_id") or await _extract_provider(task)
            if provider_id in NON_RESUMABLE_VIDEO_PROVIDERS:
                logger.warning(
                    "孤儿 video running (provider=%s 不支持 resume) → [resume_unsupported]: %s",
                    provider_id,
                    task_id,
                )
                rows = await self.queue.mark_task_failed(
                    task_id,
                    f"[resume_unsupported] provider={provider_id} 不支持接续，需手动重试以避免重复计费",
                )
                if rows == 0:
                    await self.queue.mark_task_cancelled(task_id, cancelled_by="user")
                continue

            job_id = task.get("provider_job_id")
            if not job_id:
                logger.warning("孤儿 running 无 job_id → [restart_lost]: %s", task_id)
                rows = await self.queue.mark_task_failed(
                    task_id, "[restart_lost] worker 重启时未持久化 provider_job_id"
                )
                if rows == 0:
                    await self.queue.mark_task_cancelled(task_id, cancelled_by="user")
                continue

            task["provider_id"] = provider_id
            resumable_by_provider.setdefault(provider_id, []).append(task)

        if resumable_by_provider:
            total = sum(len(v) for v in resumable_by_provider.values())
            logger.info("孤儿扫描 fast path 完成：%d 个可 resume video 任务交后台分批 dispatch", total)
            if self._orphan_dispatcher_task is not None and not self._orphan_dispatcher_task.done():
                logger.warning("旧 orphan dispatcher 仍在运行，本轮直接覆盖句柄不等待")
            self._orphan_dispatcher_task = asyncio.create_task(
                self._dispatch_resume_orphans_background(resumable_by_provider),
                name="orphan-dispatcher",
            )
        else:
            logger.info("孤儿扫描完成，无可 resume 任务")

    async def _dispatch_resume_orphans_background(
        self,
        resumable_by_provider: dict[str, list[dict[str, Any]]],
    ) -> None:
        """后台 dispatcher：按 provider 分桶并发，受 pool video_max 容量约束分批入 inflight。"""
        if self._stop_event.is_set():
            return
        sub_tasks = [
            asyncio.create_task(
                self._dispatch_provider_bucket(provider_id, tasks),
                name=f"orphan-dispatch-{provider_id}",
            )
            for provider_id, tasks in resumable_by_provider.items()
        ]
        await asyncio.gather(*sub_tasks, return_exceptions=True)
        logger.info("孤儿后台 dispatcher 完成")

    async def _dispatch_provider_bucket(
        self,
        provider_id: str,
        tasks: list[dict[str, Any]],
    ) -> None:
        """同 provider 桶并发跑 resume task，pending/inflight 分集合精确容量与 cancel 跟踪。"""
        pool = self._get_or_create_pool(provider_id)
        if pool.video_max <= 0:
            try:
                await self.reload_limits()
            except Exception:
                logger.warning("reload_limits 兜底失败", exc_info=True)
            pool = self._get_or_create_pool(provider_id)
        if pool.video_max <= 0:
            for t in tasks:
                rows = await self.queue.mark_task_failed(
                    t["task_id"],
                    f"[resume_unsupported] provider {provider_id} video_max=0",
                )
                if rows == 0:
                    await self.queue.mark_task_cancelled(t["task_id"], cancelled_by="user")
            return

        sem = asyncio.Semaphore(pool.video_max)
        capacity_lock = asyncio.Lock()

        async def _promote_pending_when_room(task_id: str) -> bool:
            """等待 provider 视频槽位真实空出，再把 pending task 晋升为 inflight。"""
            while not self._stop_event.is_set():
                async with capacity_lock:
                    pool_now = self._get_or_create_pool(provider_id)
                    if len(pool_now.video_inflight) < pool_now.video_max:
                        pool_now.video_pending.pop(task_id, None)
                        current = asyncio.current_task()
                        if current is not None:
                            pool_now.video_inflight[task_id] = current
                        return True
                await asyncio.sleep(_ORPHAN_RESUME_CAPACITY_POLL_SEC)
            return False

        async def _run_one(t: dict[str, Any]) -> None:
            task_id = t["task_id"]
            acquired = False
            try:
                await sem.acquire()
                acquired = True
                if self._stop_event.is_set():
                    return
                if not await _promote_pending_when_room(task_id):
                    return
                logger.info("已派发 resume video orphan: task_id=%s provider=%s", task_id, provider_id)
                await self._process_resume_task(t)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(self.queue.mark_task_cancelled(task_id, cancelled_by="user"))
                except Exception:
                    logger.exception("sem dispatch cancel 落终态失败 task_id=%s", task_id)
                raise
            finally:
                if acquired:
                    sem.release()
                pool_now = self._get_or_create_pool(provider_id)
                pool_now.video_pending.pop(task_id, None)
                pool_now.video_inflight.pop(task_id, None)

        sub: list[asyncio.Task] = []
        for t in tasks:
            if self._stop_event.is_set():
                break
            sub_task = asyncio.create_task(_run_one(t), name=f"resume-video-{t['task_id']}")
            pool.video_pending[t["task_id"]] = sub_task
            sub.append(sub_task)
        if sub:
            await asyncio.gather(*sub, return_exceptions=True)
