import asyncio

import pytest

from lib.friendly_errors import summarize_generation_error
from lib.generation_worker import (
    DEFAULT_PROVIDER,
    GenerationWorker,
    ProviderPool,
    _build_default_pools,
    _extract_provider,
    _read_int_env,
)


class _FakeQueue:
    def __init__(self, *, succeeded_rows: int = 1, failed_rows: int = 1):
        self.released = False
        self.succeeded = []
        self.failed = []
        self.cancelled = []
        self._lease_calls = 0
        self._succeeded_rows = succeeded_rows
        self._failed_rows = failed_rows
        self._orphans: list[dict] = []

    async def acquire_or_renew_worker_lease(self, name, owner_id, ttl_seconds):
        self._lease_calls += 1
        return True

    async def release_worker_lease(self, name, owner_id):
        self.released = True

    async def requeue_running_tasks(self):
        return 0

    async def list_orphan_tasks_on_start(self):
        return self._orphans

    async def claim_next_task(self, media_type, **_kwargs):
        return None

    async def mark_task_succeeded(self, task_id, result):
        self.succeeded.append((task_id, result))
        return self._succeeded_rows

    async def mark_task_failed(self, task_id, error):
        self.failed.append((task_id, error))
        return self._failed_rows

    async def mark_task_cancelled(self, task_id, *, cancelled_by="user"):
        self.cancelled.append((task_id, cancelled_by))
        return 1


class TestReadIntEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("ARCREEL_INT", raising=False)
        assert _read_int_env("ARCREEL_INT", 3, minimum=1) == 3

    def test_default_when_bad(self, monkeypatch):
        monkeypatch.setenv("ARCREEL_INT", "bad")
        assert _read_int_env("ARCREEL_INT", 3, minimum=1) == 3

    def test_minimum_enforced(self, monkeypatch):
        monkeypatch.setenv("ARCREEL_INT", "0")
        assert _read_int_env("ARCREEL_INT", 3, minimum=2) == 2


class TestProviderPool:
    def test_has_room(self):
        pool = ProviderPool(provider_id="test", image_max=2, video_max=1)
        assert pool.has_image_room()
        assert pool.has_video_room()

    def test_no_room_when_max_zero(self):
        pool = ProviderPool(provider_id="test", image_max=0, video_max=0)
        assert not pool.has_image_room()
        assert not pool.has_video_room()

    async def test_no_room_when_full(self):
        pool = ProviderPool(provider_id="test", image_max=1, video_max=1)
        loop = asyncio.get_running_loop()
        dummy = loop.create_future()
        dummy.set_result(None)
        pool.image_inflight["t1"] = dummy
        pool.video_inflight["t2"] = dummy
        assert not pool.has_image_room()
        assert not pool.has_video_room()

    async def test_drain_finished(self):
        pool = ProviderPool(provider_id="test", image_max=2, video_max=2)
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        done.set_result(None)
        pending = loop.create_future()
        pool.image_inflight["done1"] = done
        pool.image_inflight["pending1"] = pending
        pool.video_inflight["done2"] = done

        finished = pool.drain_finished()
        assert len(finished) == 2
        assert {task_id for task_id, _task in finished} == {"done1", "done2"}
        assert "done1" not in pool.image_inflight
        assert "pending1" in pool.image_inflight
        assert "done2" not in pool.video_inflight
        pending.cancel()


def _patch_pm(monkeypatch, project: dict | None, *, project_path=None, script: dict | None = None):
    class PM:
        def load_project(self, name):
            return project or {}

        def get_project_path(self, name):
            return project_path

        def load_script(self, name, script_file):
            return script or {}

    monkeypatch.setattr(
        "lib.config.resolver.get_project_manager",
        lambda: PM(),
    )


class TestExtractProvider:
    async def test_video_payload_provider(self):
        task = {"payload": {"video_provider": "ark"}, "task_type": "video"}
        assert await _extract_provider(task) == "ark"

    async def test_image_payload_provider(self):
        task = {"payload": {"image_provider": "gemini-vertex"}, "task_type": "storyboard"}
        assert await _extract_provider(task) == "gemini-vertex"

    async def test_default_when_unresolvable(self, monkeypatch):
        async def _raise(self, project, payload, *, capability):
            raise RuntimeError("resolver unavailable")

        monkeypatch.setattr(
            "lib.config.resolver.ConfigResolver.resolve_image_backend",
            _raise,
        )
        task = {"payload": {}}
        assert await _extract_provider(task) == DEFAULT_PROVIDER

    async def test_project_level_video_backend(self, monkeypatch):
        _patch_pm(monkeypatch, {"video_backend": "ark/seedance-1-0-pro"})
        task = {"payload": {}, "project_name": "demo", "task_type": "video"}
        assert await _extract_provider(task) == "ark"

    async def test_project_level_image_t2i(self, monkeypatch):
        _patch_pm(monkeypatch, {"image_provider_t2i": "gemini-vertex/imagen-3"})
        task = {"payload": {}, "project_name": "demo", "task_type": "storyboard"}
        assert await _extract_provider(task) == "gemini-vertex"

    async def test_character_reference_routes_to_i2i_provider(self, monkeypatch, tmp_path):
        ref_path = tmp_path / "refs" / "alice.png"
        ref_path.parent.mkdir()
        ref_path.write_bytes(b"image")
        _patch_pm(
            monkeypatch,
            {
                "image_provider_t2i": "ark/gen-1",
                "image_provider_i2i": "openai/edit-1",
                "characters": {"Alice": {"reference_image": "refs/alice.png"}},
            },
            project_path=tmp_path,
        )
        task = {
            "payload": {"prompt": "角色描述"},
            "project_name": "demo",
            "task_type": "character",
            "media_type": "image",
            "resource_id": "Alice",
        }
        assert await _extract_provider(task) == "openai"

    async def test_storyboard_sheet_reference_routes_to_i2i_provider(self, monkeypatch, tmp_path):
        sheet_path = tmp_path / "characters" / "Alice.png"
        sheet_path.parent.mkdir()
        sheet_path.write_bytes(b"image")
        _patch_pm(
            monkeypatch,
            {
                "image_provider_t2i": "ark/gen-1",
                "image_provider_i2i": "openai/edit-1",
                "characters": {"Alice": {"character_sheet": "characters/Alice.png"}},
            },
            project_path=tmp_path,
            script={
                "content_mode": "narration",
                "segments": [
                    {
                        "segment_id": "E1S01",
                        "characters_in_segment": ["Alice"],
                        "scenes": [],
                        "props": [],
                    }
                ],
            },
        )
        task = {
            "payload": {"prompt": "分镜描述", "script_file": "episode_1.json"},
            "project_name": "demo",
            "task_type": "storyboard",
            "media_type": "image",
            "resource_id": "E1S01",
            "script_file": "episode_1.json",
        }
        assert await _extract_provider(task) == "openai"

    async def test_reference_video_routes_to_video_lane(self, monkeypatch):
        _patch_pm(
            monkeypatch,
            {
                "video_backend": "ark/seedance-1-0-pro",
                "image_provider_t2i": "gemini-vertex/imagen-3",
            },
        )
        task = {"payload": {}, "project_name": "demo", "task_type": "reference_video"}
        assert await _extract_provider(task) == "ark"

    async def test_payload_provider_takes_precedence_over_project(self, monkeypatch):
        _patch_pm(monkeypatch, {"video_backend": "grok/grok-imagine-video"})
        task = {"payload": {"video_provider": "ark"}, "project_name": "demo", "task_type": "video"}
        assert await _extract_provider(task) == "ark"

    async def test_deleted_project_load_failure_falls_back_not_raises(self, monkeypatch):
        def _raising_pm():
            def _load(self, name):
                raise FileNotFoundError(name)

            return type("PM", (), {"load_project": _load})()

        monkeypatch.setattr("lib.config.resolver.get_project_manager", _raising_pm)
        task = {"payload": {}, "project_name": "deleted-proj", "task_type": "video"}
        assert await _extract_provider(task) == DEFAULT_PROVIDER


class TestExtractProviderAlignsWithExecution:
    async def test_image_alignment(self, monkeypatch):
        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        project = {"image_provider_t2i": "openai/gen-1", "image_provider_i2i": "openai/edit-1"}
        _patch_pm(monkeypatch, project)
        task = {"payload": {}, "project_name": "demo", "task_type": "storyboard"}

        worker_provider = await _extract_provider(task)
        resolved = await ConfigResolver(async_session_factory).resolve_image_backend(project, {}, capability="t2i")
        assert worker_provider == resolved.provider_id == "openai"

    async def test_video_alignment(self, monkeypatch):
        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        project = {"video_backend": "ark/seedance-1-0-pro"}
        _patch_pm(monkeypatch, project)
        task = {"payload": {}, "project_name": "demo", "task_type": "video"}

        worker_provider = await _extract_provider(task)
        resolved = await ConfigResolver(async_session_factory).resolve_video_backend(project, {})
        assert worker_provider == resolved.provider_id == "ark"


class TestBuildDefaultPools:
    def test_builds_default_pool(self, monkeypatch):
        monkeypatch.delenv("IMAGE_MAX_WORKERS", raising=False)
        monkeypatch.delenv("VIDEO_MAX_WORKERS", raising=False)
        pools = _build_default_pools()
        assert DEFAULT_PROVIDER in pools
        assert pools[DEFAULT_PROVIDER].image_max == 5
        assert pools[DEFAULT_PROVIDER].video_max == 3

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("IMAGE_MAX_WORKERS", "5")
        monkeypatch.setenv("VIDEO_MAX_WORKERS", "4")
        pools = _build_default_pools()
        assert pools[DEFAULT_PROVIDER].image_max == 5
        assert pools[DEFAULT_PROVIDER].video_max == 4


class TestGenerationWorker:
    @pytest.mark.asyncio
    async def test_process_task_success_and_failure(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _fake_execute(task):
            return {"ok": task["task_id"]}

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _fake_execute)
        await worker._process_task({"task_id": "t1"})
        assert queue.succeeded == [("t1", {"ok": "t1"})]

        async def _raise(_task):
            raise RuntimeError("boom")

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _raise)
        await worker._process_task({"task_id": "t2"})
        assert queue.failed and queue.failed[0][0] == "t2"

    @pytest.mark.asyncio
    async def test_process_task_persists_friendly_quota_error(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _raise(_task):
            raise RuntimeError(
                "Ark 视频生成失败: ContentGenerationError(message='Your account [2100778485] has reached the "
                "set inference limit for the [doubao-seedance-1-0-pro] model, and the model service has been "
                "paused. To continue using this model, please visit the Model Activation page to adjust or close "
                'the "Safe Experience Mode". Request id: 02177967014802800000000000000000000ffffac15d1c830f90a\', '
                "code='SetLimitExceeded')"
            )

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _raise)
        await worker._process_task(
            {
                "task_id": "t-quota",
                "task_type": "video",
                "media_type": "video",
                "payload": {"video_provider": "ark"},
            }
        )

        assert queue.failed and queue.failed[0][0] == "t-quota"
        message = queue.failed[0][1]
        assert "模型已达到后台设置的推理上限" in message
        assert "Safe Experience Mode" in message
        assert "供应商：ark" in message
        assert "模型：doubao-seedance-1-0-pro" in message
        assert "错误码：SetLimitExceeded" in message
        assert "请求 ID：02177967014802800000000000000000000ffffac15d1c830f90a" in message

    @pytest.mark.asyncio
    async def test_process_task_cancelled_error_marks_cancelled(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _cancelled(_task):
            raise asyncio.CancelledError

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _cancelled)
        with pytest.raises(asyncio.CancelledError):
            await worker._process_task({"task_id": "tc"})
        assert queue.cancelled and queue.cancelled[0][0] == "tc"

    @pytest.mark.asyncio
    async def test_drain_finished_tasks_consumes_cancelled_child_task(self):
        queue = _FakeQueue()
        pool = ProviderPool(provider_id="test", image_max=1, video_max=1)
        worker = GenerationWorker(queue=queue, pools={"test": pool})

        async def _cancelled_child():
            raise asyncio.CancelledError

        task = asyncio.create_task(_cancelled_child())
        await asyncio.sleep(0)
        pool.image_inflight["tc"] = task

        await worker._drain_finished_tasks()

        assert "tc" not in pool.image_inflight
        assert queue.cancelled == [("tc", "user")]

    @pytest.mark.asyncio
    async def test_process_task_zero_rows_succeeded_falls_through_to_cancelled(self, monkeypatch):
        queue = _FakeQueue(succeeded_rows=0)
        worker = GenerationWorker(queue=queue)

        async def _ok(_task):
            return {"result": "ok"}

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _ok)
        await worker._process_task({"task_id": "t0rows"})
        assert queue.succeeded == [("t0rows", {"result": "ok"})]
        assert queue.cancelled and queue.cancelled[0][0] == "t0rows"

    @pytest.mark.asyncio
    async def test_request_cancel_signals_inflight_task(self):
        queue = _FakeQueue()
        pool = ProviderPool(provider_id="test", image_max=1, video_max=1)
        worker = GenerationWorker(queue=queue, pools={"test": pool})

        async def _long():
            await asyncio.sleep(10)

        t = asyncio.create_task(_long())
        pool.video_inflight["tid"] = t

        assert worker.request_cancel("tid") is True
        await asyncio.sleep(0)
        assert t.cancelled() or t.done()
        assert worker.request_cancel("ghost") is False

    @pytest.mark.asyncio
    async def test_handle_orphan_cancelling_marks_cancelled(self):
        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "orphan-cancelling",
                "status": "cancelling",
                "provider_id": None,
                "provider_job_id": None,
                "media_type": "video",
                "task_type": "video",
                "payload": {},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        await worker._handle_orphan_tasks_on_start()
        assert queue.cancelled and queue.cancelled[0][0] == "orphan-cancelling"

    @pytest.mark.asyncio
    async def test_handle_orphan_running_no_job_id_marks_restart_lost(self):
        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "orphan-lost",
                "status": "running",
                "provider_id": None,
                "provider_job_id": None,
                "media_type": "video",
                "task_type": "video",
                "payload": {},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        await worker._handle_orphan_tasks_on_start()
        assert queue.failed and queue.failed[0][0] == "orphan-lost"
        assert "[restart_lost]" in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_start_stop_run_loop_releases_lease(self):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)
        worker.heartbeat_interval = 0.01
        worker.poll_interval = 0.01

        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

        assert queue.released
        assert worker._main_task is None

    def test_backward_compat_image_video_workers(self):
        pools = {
            "a": ProviderPool(provider_id="a", image_max=3, video_max=2),
            "b": ProviderPool(provider_id="b", image_max=1, video_max=0),
        }
        worker = GenerationWorker(queue=_FakeQueue(), pools=pools)
        assert worker.image_workers == 4
        assert worker.video_workers == 2

    def test_reload_limits_from_env(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)
        monkeypatch.setenv("IMAGE_MAX_WORKERS", "10")
        monkeypatch.setenv("VIDEO_MAX_WORKERS", "8")
        worker.reload_limits_from_env()
        assert worker._pools[DEFAULT_PROVIDER].image_max == 10
        assert worker._pools[DEFAULT_PROVIDER].video_max == 8

    def test_get_or_create_pool_unknown(self):
        worker = GenerationWorker(queue=_FakeQueue())
        pool = worker._get_or_create_pool("unknown-provider")
        assert pool.provider_id == "unknown-provider"
        assert pool.image_max == 5
        assert pool.video_max == 3
        assert "unknown-provider" in worker._pools

    async def test_any_pool_has_room(self):
        pools = {
            "a": ProviderPool(provider_id="a", image_max=0, video_max=1),
            "b": ProviderPool(provider_id="b", image_max=1, video_max=0),
        }
        worker = GenerationWorker(queue=_FakeQueue(), pools=pools)
        assert worker._any_pool_has_room("image")
        assert worker._any_pool_has_room("video")
        loop = asyncio.get_running_loop()
        dummy = loop.create_future()
        dummy.set_result(None)
        pools["b"].image_inflight["t1"] = dummy
        assert not worker._any_pool_has_room("image")

    @pytest.mark.asyncio
    async def test_claim_tasks_dispatches_to_correct_pool(self, monkeypatch):
        class _ClaimableQueue(_FakeQueue):
            def __init__(self):
                super().__init__()
                self._tasks = [
                    {
                        "task_id": "img1",
                        "task_type": "gen_image",
                        "media_type": "image",
                        "payload": {"image_provider": "gemini-aistudio"},
                    },
                    {
                        "task_id": "vid1",
                        "task_type": "gen_video",
                        "media_type": "video",
                        "payload": {"video_provider": "ark"},
                    },
                ]

            async def claim_next_task(self, media_type, **_kwargs):  # type: ignore[override]
                for i, t in enumerate(self._tasks):
                    if t["media_type"] == media_type:
                        return self._tasks.pop(i)
                return None

        queue = _ClaimableQueue()
        pools = {
            "gemini-aistudio": ProviderPool(provider_id="gemini-aistudio", image_max=3, video_max=2),
            "ark": ProviderPool(provider_id="ark", image_max=0, video_max=2),
        }
        worker = GenerationWorker(queue=queue, pools=pools)

        async def _fake_execute(task):
            return {"ok": True}

        monkeypatch.setattr("server.services.generation_tasks.execute_generation_task", _fake_execute)

        claimed = await worker._claim_tasks()
        assert claimed
        assert "img1" in pools["gemini-aistudio"].image_inflight
        assert "vid1" in pools["ark"].video_inflight

        await asyncio.gather(
            *[
                *pools["gemini-aistudio"].image_inflight.values(),
                *pools["ark"].video_inflight.values(),
            ],
            return_exceptions=True,
        )

    def test_pool_full_providers_excludes_max_zero(self):
        pools = {
            "video-only": ProviderPool(provider_id="video-only", image_max=0, video_max=2),
            "img-full": ProviderPool(provider_id="img-full", image_max=1, video_max=0),
        }
        loop = asyncio.new_event_loop()
        dummy = loop.create_future()
        dummy.set_result(None)
        pools["img-full"].image_inflight["t1"] = dummy

        worker = GenerationWorker(queue=_FakeQueue(), pools=pools)
        full_image = worker._pool_full_providers("image")
        assert "img-full" in full_image
        assert "video-only" not in full_image

        full_video = worker._pool_full_providers("video")
        assert "img-full" not in full_video
        assert "video-only" not in full_video
        loop.close()

    @pytest.mark.asyncio
    async def test_handle_orphan_image_running_marks_restart_lost(self, monkeypatch):
        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "img-orphan",
                "status": "running",
                "provider_id": "gemini-aistudio",
                "provider_job_id": "should-not-be-used",
                "media_type": "image",
                "task_type": "storyboard",
                "payload": {},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        requeued: list[str] = []

        async def _capture_requeue(self, task_id):
            requeued.append(task_id)

        monkeypatch.setattr(GenerationWorker, "_requeue_single_task", _capture_requeue)
        await worker._handle_orphan_tasks_on_start()
        assert requeued == []
        assert queue.failed and queue.failed[0][0] == "img-orphan"
        assert "[restart_lost]" in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_handle_orphan_non_resumable_video_marks_resume_unsupported(self, monkeypatch):
        from lib.providers import PROVIDER_GROK

        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "grok-orphan",
                "status": "running",
                "provider_id": PROVIDER_GROK,
                "provider_job_id": "some-job",
                "media_type": "video",
                "task_type": "video",
                "payload": {},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        requeued: list[str] = []

        async def _capture_requeue(self, task_id):
            requeued.append(task_id)

        monkeypatch.setattr(GenerationWorker, "_requeue_single_task", _capture_requeue)
        await worker._handle_orphan_tasks_on_start()
        assert requeued == []
        assert queue.failed and queue.failed[0][0] == "grok-orphan"
        assert "[resume_unsupported]" in queue.failed[0][1]
        assert PROVIDER_GROK in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_handle_orphan_discard_paths_fallback_to_cancelled_on_zero_rows(self, monkeypatch):
        from lib.providers import PROVIDER_GROK

        queue = _FakeQueue(failed_rows=0)
        queue._orphans = [
            {
                "task_id": "img-raced",
                "status": "running",
                "provider_id": "gemini-aistudio",
                "provider_job_id": None,
                "media_type": "image",
                "task_type": "storyboard",
                "payload": {},
                "project_name": "demo",
            },
            {
                "task_id": "grok-raced",
                "status": "running",
                "provider_id": PROVIDER_GROK,
                "provider_job_id": "job",
                "media_type": "video",
                "task_type": "video",
                "payload": {},
                "project_name": "demo",
            },
        ]
        worker = GenerationWorker(queue=queue)
        await worker._handle_orphan_tasks_on_start()
        cancelled_ids = {tid for tid, _by in queue.cancelled}
        assert cancelled_ids == {"img-raced", "grok-raced"}

    @pytest.mark.asyncio
    async def test_handle_orphan_uses_persisted_provider_id(self, monkeypatch):
        from lib.providers import PROVIDER_GROK

        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "ghost-orphan",
                "status": "running",
                "provider_id": PROVIDER_GROK,
                "provider_job_id": "stale-job",
                "media_type": "video",
                "task_type": "video",
                "payload": {"video_provider": "ark"},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        requeued: list[str] = []
        resume_dispatched: list[str] = []

        async def _capture_requeue(self, task_id):
            requeued.append(task_id)

        async def _capture_resume(self, task):
            resume_dispatched.append(task["task_id"])

        monkeypatch.setattr(GenerationWorker, "_requeue_single_task", _capture_requeue)
        monkeypatch.setattr(GenerationWorker, "_process_resume_task", _capture_resume)
        await worker._handle_orphan_tasks_on_start()
        assert requeued == []
        assert resume_dispatched == []
        assert queue.failed and queue.failed[0][0] == "ghost-orphan"
        assert "[resume_unsupported]" in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_handle_orphan_resumable_dispatches_process_resume_task(self, monkeypatch):
        queue = _FakeQueue()
        queue._orphans = [
            {
                "task_id": "ark-orphan",
                "status": "running",
                "provider_id": "ark",
                "provider_job_id": "ark-job-1",
                "media_type": "video",
                "task_type": "video",
                "payload": {},
                "project_name": "demo",
            }
        ]
        worker = GenerationWorker(queue=queue)
        dispatched: list[dict] = []

        async def _capture_resume(self, task):
            dispatched.append(task)

        monkeypatch.setattr(GenerationWorker, "_process_resume_task", _capture_resume)
        await worker._handle_orphan_tasks_on_start()
        for _ in range(20):
            await asyncio.sleep(0)
            if dispatched:
                break
        for t in list(asyncio.all_tasks()):
            name = t.get_name()
            if (
                name in ("orphan-dispatcher",)
                or name.startswith("orphan-dispatch-")
                or name.startswith("resume-video-")
            ):
                try:
                    await t
                except Exception:
                    pass
        assert len(dispatched) == 1
        assert dispatched[0]["task_id"] == "ark-orphan"

    @pytest.mark.asyncio
    async def test_resume_orphan_dispatch_waits_for_existing_video_capacity(self, monkeypatch):
        monkeypatch.setattr("lib.generation_worker._ORPHAN_RESUME_CAPACITY_POLL_SEC", 0.01)
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)
        pool = ProviderPool(provider_id="ark", image_max=0, video_max=1)
        worker._pools["ark"] = pool

        blocker = asyncio.create_task(asyncio.sleep(60), name="live-video")
        pool.video_inflight["live-video"] = blocker
        dispatched: list[str] = []

        async def _capture_resume(self, task):
            dispatched.append(task["task_id"])

        monkeypatch.setattr(GenerationWorker, "_process_resume_task", _capture_resume)
        task = {
            "task_id": "ark-orphan",
            "status": "running",
            "provider_id": "ark",
            "provider_job_id": "ark-job-1",
            "media_type": "video",
            "task_type": "video",
            "payload": {},
            "project_name": "demo",
        }

        dispatcher = asyncio.create_task(worker._dispatch_provider_bucket("ark", [task]))
        await asyncio.sleep(0.03)
        assert dispatched == []
        assert "ark-orphan" in pool.video_pending

        pool.video_inflight.pop("live-video")
        await dispatcher
        assert dispatched == ["ark-orphan"]

        blocker.cancel()
        try:
            await blocker
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_process_resume_task_locks_persisted_provider_to_payload(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)
        captured_task: dict | None = None

        async def _fake_execute(task, *, job_id):
            nonlocal captured_task
            captured_task = task
            return {"ok": True}

        monkeypatch.setattr("server.services.resume_executor.execute_resume_video_task", _fake_execute)

        task = {
            "task_id": "resume-locked",
            "task_type": "video",
            "media_type": "video",
            "provider_id": "openai",
            "provider_job_id": "openai-job",
            "payload": {"video_provider": "gemini-aistudio"},
            "project_name": "demo",
        }
        await worker._process_resume_task(task)
        assert captured_task is not None
        assert captured_task["payload"]["video_provider"] == "openai"
        assert queue.succeeded == [("resume-locked", {"ok": True})]

    @pytest.mark.asyncio
    async def test_process_resume_task_resume_expired(self, monkeypatch):
        from lib.video_backends.base import ResumeExpiredError

        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _expire(_task, *, job_id):
            raise ResumeExpiredError(job_id="x", provider="ark")

        monkeypatch.setattr("server.services.resume_executor.execute_resume_video_task", _expire)
        task = {
            "task_id": "exp",
            "task_type": "video",
            "media_type": "video",
            "provider_id": "ark",
            "provider_job_id": "x",
            "payload": {},
            "project_name": "demo",
        }
        await worker._process_resume_task(task)
        assert queue.failed and queue.failed[0][0] == "exp"
        assert "[resume_expired]" in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_process_resume_task_resume_unsupported(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _unsup(_task, *, job_id):
            raise NotImplementedError("no resume_video")

        monkeypatch.setattr("server.services.resume_executor.execute_resume_video_task", _unsup)
        task = {
            "task_id": "uns",
            "task_type": "video",
            "media_type": "video",
            "provider_id": "vidu",
            "provider_job_id": "x",
            "payload": {},
            "project_name": "demo",
        }
        await worker._process_resume_task(task)
        assert queue.failed and queue.failed[0][0] == "uns"
        assert "[resume_unsupported]" in queue.failed[0][1]

    @pytest.mark.asyncio
    async def test_process_resume_task_generic_exception(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _boom(_task, *, job_id):
            raise RuntimeError("transient backend error")

        monkeypatch.setattr("server.services.resume_executor.execute_resume_video_task", _boom)
        task = {
            "task_id": "boom",
            "task_type": "video",
            "media_type": "video",
            "provider_id": "ark",
            "provider_job_id": "x",
            "payload": {},
            "project_name": "demo",
        }
        await worker._process_resume_task(task)
        assert queue.failed and queue.failed[0][0] == "boom"
        assert not queue.failed[0][1].startswith("[resume_")

    @pytest.mark.asyncio
    async def test_process_resume_task_cancelled_error(self, monkeypatch):
        queue = _FakeQueue()
        worker = GenerationWorker(queue=queue)

        async def _cancel(_task, *, job_id):
            raise asyncio.CancelledError

        monkeypatch.setattr("server.services.resume_executor.execute_resume_video_task", _cancel)
        task = {
            "task_id": "rc",
            "task_type": "video",
            "media_type": "video",
            "provider_id": "ark",
            "provider_job_id": "x",
            "payload": {},
            "project_name": "demo",
        }
        with pytest.raises(asyncio.CancelledError):
            await worker._process_resume_task(task)
        assert queue.cancelled and queue.cancelled[0][0] == "rc"


class TestFriendlyGenerationErrors:
    def test_summarizes_generic_quota_errors(self):
        message = summarize_generation_error(
            "Error code: insufficient_quota - billing quota exceeded",
            provider_id="openai",
            task={"payload": {"model": "gpt-image-1"}},
        )
        assert "用量、余额或配额已达上限" in message
        assert "供应商：openai" in message
        assert "模型：gpt-image-1" in message

    def test_summarizes_rate_limit_errors(self):
        message = summarize_generation_error(
            "429 Too Many Requests: rate limit exceeded",
            provider_id="gemini-aistudio",
        )
        assert "请求频率或并发已超限" in message
        assert "供应商：gemini-aistudio" in message

    def test_keeps_model_not_found_errors_unchanged(self):
        raw = "InvalidEndpointOrModel.NotFound: 模型不存在，或当前账号没有访问权限"
        assert summarize_generation_error(raw, provider_id="ark") == raw

    def test_passes_unknown_errors_through(self):
        assert summarize_generation_error("boom") == "boom"
