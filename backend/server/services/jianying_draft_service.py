"""剪映草稿导出服务

将 ArcReel 单集已生成的视频片段导出为剪映草稿 ZIP。
使用 pyJianYingDraft 库生成 draft_content.json，
后处理路径替换使草稿指向用户本地剪映目录。
"""

import json
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyJianYingDraft as draft
from pyJianYingDraft import (
    ClipSettings,
    TextBorder,
    TextSegment,
    TextShadow,
    TextStyle,
    TrackType,
    TransitionType,
    VideoMaterial,
    VideoSegment,
    trange,
)

# transition_to_next schema 值 → 剪映 TransitionType。"cut" 不挂转场。
_TRANSITION_MAP: dict[str, TransitionType] = {
    "fade": TransitionType.闪黑,
    "dissolve": TransitionType.叠化,
}

from lib.project_manager import ProjectManager
from lib.script_splitting_templates import script_splitting_asset_metadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JianyingDraftExportResult:
    """剪映草稿导出结果。"""

    path: Path
    summary: dict[str, Any]


class JianyingDraftService:
    """剪映草稿导出服务"""

    def __init__(self, project_manager: ProjectManager):
        self.pm = project_manager

    # ------------------------------------------------------------------
    # 内部方法：数据提取
    # ------------------------------------------------------------------

    def _find_episode_script(self, project_name: str, project: dict, episode: int) -> tuple[dict, str]:
        """定位指定集的剧本文件，返回 (script_dict, filename)"""
        episodes = project.get("episodes", [])
        ep_entry = next((e for e in episodes if e.get("episode") == episode), None)
        if ep_entry is None:
            raise FileNotFoundError(f"第 {episode} 集不存在")

        script_file = ep_entry.get("script_file", "")
        filename = Path(script_file).name
        script_data = self.pm.load_script(project_name, filename)
        return script_data, filename

    @staticmethod
    def _is_reference_video_script(script: dict[str, Any]) -> bool:
        return JianyingDraftService._video_item_kind(script)[0] == "video_units"

    @staticmethod
    def _video_item_kind(script: dict[str, Any]) -> tuple[str, str, str]:
        if script.get("generation_mode") == "reference_video":
            return "video_units", "unit_id", "reference_videos"
        if "video_units" in script and "segments" not in script and "scenes" not in script:
            return "video_units", "unit_id", "reference_videos"

        content_mode = script.get("content_mode")
        if content_mode == "drama":
            return "scenes", "scene_id", "videos"
        if content_mode == "narration":
            if "segments" not in script and "scenes" in script:
                return "scenes", "scene_id", "videos"
            return "segments", "segment_id", "videos"

        if "scenes" in script and "segments" not in script:
            return "scenes", "scene_id", "videos"
        return "segments", "segment_id", "videos"

    def _video_items(self, script: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
        """返回当前剧本中应该参与视频导出的项目、ID 字段和资源类型。"""
        item_key, id_field, resource_type = self._video_item_kind(script)
        items = script.get(item_key) or []
        safe_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        return safe_items, id_field, resource_type

    def _collect_video_export_plan(
        self,
        script: dict[str, Any],
        project_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """收集已出片视频，并记录未生成 / 文件缺失的项目。"""
        items, id_field, resource_type = self._video_items(script)
        project_root = project_dir.resolve()
        clips = []
        missing_items = []
        for index, item in enumerate(items):
            item_id = str(item.get(id_field) or f"{resource_type}_{index + 1}")
            assets = item.get("generated_assets") or {}
            video_clip = assets.get("video_clip") if isinstance(assets, dict) else None
            missing_base = {
                "id": item_id,
                "resource_type": resource_type,
            }
            if not video_clip:
                missing_items.append({**missing_base, "reason": "not_generated"})
                continue

            try:
                abs_path = (project_dir / str(video_clip)).resolve()
            except Exception:
                logger.warning("video_clip 路径无效，已跳过: %s", video_clip, exc_info=True)
                missing_items.append({**missing_base, "reason": "path_invalid", "video_clip": str(video_clip)})
                continue
            if not abs_path.is_relative_to(project_root):
                logger.warning("video_clip 路径越界，已跳过: %s", video_clip)
                missing_items.append({**missing_base, "reason": "path_invalid", "video_clip": str(video_clip)})
                continue
            if not abs_path.is_file():
                missing_items.append({**missing_base, "reason": "file_missing", "video_clip": str(video_clip)})
                continue

            version_metadata = self._get_current_version_metadata(project_dir, resource_type, str(item_id))
            clip = {
                "id": item_id,
                "duration_seconds": item.get("duration_seconds", 8),
                "video_clip": str(video_clip),
                "abs_path": abs_path,
                "novel_text": item.get("novel_text", ""),
                "resource_type": resource_type,
                "transition_to_next": item.get("transition_to_next", "cut"),
            }
            if version_metadata:
                clip["version_metadata"] = version_metadata
                generation_quality = version_metadata.get("generation_quality")
                if generation_quality:
                    clip["generation_quality"] = generation_quality
            clips.append(clip)

        return clips, missing_items

    def _collect_video_clips(self, script: dict, project_dir: Path) -> list[dict[str, Any]]:
        """从剧本中提取已完成视频的片段列表"""
        clips, _ = self._collect_video_export_plan(script, project_dir)
        return clips

    @staticmethod
    def _build_export_summary(
        episode: int,
        clips: list[dict[str, Any]],
        missing_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        exported_ids = [str(clip.get("id") or "") for clip in clips if str(clip.get("id") or "")]
        missing_ids = [str(item.get("id") or "") for item in missing_items if str(item.get("id") or "")]
        return {
            "episode": episode,
            "total_count": len(clips) + len(missing_items),
            "exported_count": len(clips),
            "missing_count": len(missing_items),
            "exported_ids": exported_ids,
            "missing_ids": missing_ids,
            "missing_items": missing_items,
        }

    @staticmethod
    def _build_export_manifest(
        *,
        project_name: str,
        episode: int,
        project: dict[str, Any],
        script: dict[str, Any],
        script_file: str,
        clips: list[dict[str, Any]],
    ) -> dict[str, Any]:
        script_meta = script.get("metadata") if isinstance(script.get("metadata"), dict) else {}
        video_version_map: dict[str, Any] = {}
        for clip in clips:
            clip_id = str(clip.get("id") or "")
            if not clip_id:
                continue
            version_meta = clip.get("version_metadata")
            version_meta = version_meta if isinstance(version_meta, dict) else {}
            video_version_map[clip_id] = {
                "resource_type": clip.get("resource_type"),
                "video_clip": clip.get("video_clip"),
                "version": version_meta.get("version"),
                "storyboard_version": version_meta.get("storyboard_version"),
                "provider_capability_hash": version_meta.get("provider_capability_hash"),
                "script_splitting_hash": version_meta.get("script_splitting_hash"),
                "script_splitting_template_id": version_meta.get("script_splitting_template_id"),
            }

        manifest = {
            "kind": "manju_jianying_export_manifest",
            "project_name": project_name,
            "episode": episode,
            "script_file": script_file,
            "script_version": script_meta.get("updated_at") or script_meta.get("created_at"),
            "video_version_map": video_version_map,
        }
        manifest.update(script_splitting_asset_metadata(project))
        if script.get("script_splitting_hash"):
            manifest.setdefault("script_splitting_hash", script.get("script_splitting_hash"))
        return manifest

    @staticmethod
    def _get_current_version_metadata(project_dir: Path, resource_type: str, resource_id: str) -> dict[str, Any]:
        versions_path = project_dir / "versions" / "versions.json"
        if not versions_path.is_file():
            return {}
        try:
            payload = json.loads(versions_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("读取版本元数据失败，跳过质量信息: %s", versions_path, exc_info=True)
            return {}

        resource_info = payload.get(resource_type, {}).get(resource_id)
        if not isinstance(resource_info, dict):
            return {}
        versions = resource_info.get("versions")
        if not isinstance(versions, list):
            return {}

        current_version = resource_info.get("current_version")
        for item in versions:
            if isinstance(item, dict) and item.get("version") == current_version:
                return item
        for item in reversed(versions):
            if isinstance(item, dict):
                return item
        return {}

    @classmethod
    def _assert_export_ready(cls, project: dict[str, Any], clips: list[dict[str, Any]], episode: int) -> None:
        """保留旧私有入口；剪映导出现在允许草稿/低分辨率视频参与合成。"""
        return

    def _resolve_canvas_size(self, project: dict, first_video_path: Path | None = None) -> tuple[int, int]:
        """根据项目 aspect_ratio 确定画布尺寸，缺失时从首个视频自动检测"""
        ar = project.get("aspect_ratio")
        aspect = ar if isinstance(ar, str) else (ar.get("video") if isinstance(ar, dict) else None)
        if aspect is None and first_video_path is not None:
            mat = VideoMaterial(str(first_video_path))
            aspect = "9:16" if mat.height > mat.width else "16:9"
        if aspect == "9:16":
            return 1080, 1920
        return 1920, 1080

    # ------------------------------------------------------------------
    # 内部方法：草稿生成
    # ------------------------------------------------------------------

    def _generate_draft(
        self,
        *,
        draft_dir: Path,
        draft_name: str,
        clips: list[dict],
        width: int,
        height: int,
        content_mode: str,
    ) -> None:
        """使用 pyJianYingDraft 在 draft_dir 中生成草稿文件"""
        draft_dir.parent.mkdir(parents=True, exist_ok=True)
        folder = draft.DraftFolder(str(draft_dir.parent))
        script_file = folder.create_draft(draft_name, width=width, height=height, allow_replace=True)

        # 视频轨
        script_file.add_track(TrackType.video)

        # 字幕轨（仅 narration 模式）
        has_subtitle = content_mode == "narration"
        text_style: TextStyle | None = None
        text_border: TextBorder | None = None
        text_shadow: TextShadow | None = None
        subtitle_position: ClipSettings | None = None
        is_portrait = height > width
        if has_subtitle:
            script_file.add_track(TrackType.text, "字幕")
            text_style = TextStyle(
                size=12.0 if is_portrait else 8.0,
                color=(1.0, 1.0, 1.0),
                align=1,
                bold=True,
                auto_wrapping=True,
                max_line_width=0.82 if is_portrait else 0.6,
            )
            text_border = TextBorder(
                color=(0.0, 0.0, 0.0),
                width=30.0,
            )
            text_shadow = TextShadow(
                color=(0.0, 0.0, 0.0),
                alpha=0.7,
                diffuse=8.0,
                distance=3.0,
                angle=-45.0,
            )
            subtitle_position = ClipSettings(
                transform_y=-0.75 if is_portrait else -0.8,
            )

        # 逐片段添加
        offset_us = 0
        last_index = len(clips) - 1
        for index, clip in enumerate(clips):
            # 预读实际视频时长
            material = VideoMaterial(clip["local_path"])
            actual_duration_us = material.duration

            # 视频片段
            video_seg = VideoSegment(
                material,
                trange(offset_us, actual_duration_us),
            )

            # 转场：剪映约定挂在前一段上，因此最后一段不挂；cut 不挂。
            if index < last_index:
                transition_type = _TRANSITION_MAP.get(clip.get("transition_to_next", "cut"))
                if transition_type is not None:
                    video_seg.add_transition(transition_type)

            script_file.add_segment(video_seg)

            # 字幕片段
            if has_subtitle and clip.get("novel_text"):
                text_seg = TextSegment(
                    text=clip["novel_text"],
                    timerange=trange(offset_us, actual_duration_us),
                    style=text_style,
                    border=text_border,
                    shadow=text_shadow,
                    clip_settings=subtitle_position,
                )
                script_file.add_segment(text_seg)

            offset_us += actual_duration_us

        script_file.save()

    def _replace_paths_in_draft(self, *, json_path: Path, tmp_prefix: str, target_prefix: str) -> None:
        """JSON 安全地替换 draft_content.json 中的临时路径"""
        real = os.path.realpath(json_path)
        tmp = os.path.realpath(tempfile.gettempdir()) + os.sep
        if not real.startswith(tmp):
            raise ValueError(f"路径越界，拒绝写入: {real}")

        with open(real, encoding="utf-8") as f:  # noqa: PTH123
            data = json.load(f)

        def _walk(obj: Any) -> Any:
            if isinstance(obj, str) and tmp_prefix in obj:
                return obj.replace(tmp_prefix, target_prefix)
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(v) for v in obj]
            return obj

        data = _walk(data)
        with open(real, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(data, f, ensure_ascii=False)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_draft_name(project: dict, project_name: str, episode: int) -> str:
        raw_title = str(project.get("title") or project_name)
        safe_title = raw_title
        for char in ('<', '>', ':', '"', '/', "\\", "|", "?", "*"):
            safe_title = safe_title.replace(char, "_")
        safe_title = safe_title.replace("..", "_").strip(" .") or project_name
        return f"{safe_title}_第{episode}集"

    @staticmethod
    def _unique_draft_dir(draft_root: Path, draft_name: str) -> tuple[Path, str]:
        target = draft_root / draft_name
        if not target.exists():
            return target, draft_name

        index = 2
        while True:
            candidate_name = f"{draft_name}_{index}"
            candidate = draft_root / candidate_name
            if not candidate.exists():
                return candidate, candidate_name
            index += 1

    @staticmethod
    def _draft_assets_prefix(draft_path: str, draft_name: str) -> str:
        normalized = draft_path.rstrip("/\\")
        return f"{normalized}/{draft_name}/assets"

    def _prepare_episode_draft_dir(
        self,
        project_name: str,
        episode: int,
        draft_path: str,
        *,
        draft_name: str | None = None,
        use_draft_info_name: bool = True,
    ) -> tuple[Path, Path, str, dict[str, Any]]:
        project = self.pm.load_project(project_name)
        project_dir = self.pm.get_project_path(project_name)

        # 1. 定位剧本
        script_data, script_filename = self._find_episode_script(project_name, project, episode)

        # 2. 收集已完成视频
        content_mode = script_data.get("content_mode", "narration")
        clips, missing_items = self._collect_video_export_plan(script_data, project_dir)
        if not clips:
            raise ValueError(f"第 {episode} 集没有已完成的视频片段，请先生成视频")
        summary = self._build_export_summary(episode, clips, missing_items)
        export_manifest = self._build_export_manifest(
            project_name=project_name,
            episode=episode,
            project=project,
            script=script_data,
            script_file=script_filename,
            clips=clips,
        )

        # 3. 画布尺寸（项目未设 aspect_ratio 时从首个视频自动检测）
        width, height = self._resolve_canvas_size(project, clips[0]["abs_path"])

        # 4. 创建临时目录 + 复制素材到暂存区
        resolved_draft_name = draft_name or self._safe_draft_name(project, project_name, episode)
        tmp_dir = Path(tempfile.mkdtemp(prefix="arcreel_jy_"))
        try:
            staging_dir = tmp_dir / "staging"
            staging_dir.mkdir()

            local_clips = []
            for clip in clips:
                src = clip["abs_path"]
                dst = staging_dir / src.name
                try:
                    dst.hardlink_to(src)
                except OSError:
                    shutil.copy2(src, dst)
                local_clips.append({**clip, "local_path": str(dst)})

            # 5. 生成草稿（create_draft 会重建 draft_dir）
            draft_dir = tmp_dir / resolved_draft_name
            self._generate_draft(
                draft_dir=draft_dir,
                draft_name=resolved_draft_name,
                clips=local_clips,
                width=width,
                height=height,
                content_mode=content_mode,
            )

            # 6. 将素材移入草稿目录
            assets_dir = draft_dir / "assets"
            assets_dir.mkdir(exist_ok=True)
            for clip in local_clips:
                src = Path(clip["local_path"])
                dst = assets_dir / src.name
                shutil.move(str(src), str(dst))

            # 7. 路径后处理：staging 路径 → 用户本地路径
            draft_content_path = draft_dir / "draft_content.json"
            self._replace_paths_in_draft(
                json_path=draft_content_path,
                tmp_prefix=str(staging_dir),
                target_prefix=self._draft_assets_prefix(draft_path, resolved_draft_name),
            )

            # 8. 剪映 6+ 使用 draft_info.json，低版本使用 draft_content.json
            if use_draft_info_name:
                draft_content_path.rename(draft_dir / "draft_info.json")
            (draft_dir / "manju_export_manifest.json").write_text(
                json.dumps(export_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            return tmp_dir, draft_dir, resolved_draft_name, summary
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def export_episode_draft(
        self,
        project_name: str,
        episode: int,
        draft_path: str,
        *,
        use_draft_info_name: bool = True,
    ) -> Path:
        """
        导出指定集的剪映草稿 ZIP。

        Returns:
            ZIP 文件路径（临时文件，调用方负责清理）

        Raises:
            FileNotFoundError: 项目或剧本不存在
            ValueError: 无可导出的视频片段
        """
        tmp_dir, draft_dir, draft_name, _ = self._prepare_episode_draft_dir(
            project_name,
            episode,
            draft_path,
            use_draft_info_name=use_draft_info_name,
        )
        try:
            zip_path = tmp_dir / f"{draft_name}.zip"
            video_suffixes = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
            with zipfile.ZipFile(zip_path, "w") as zf:
                for file in draft_dir.rglob("*"):
                    if file.is_file():
                        arcname = f"{draft_name}/{file.relative_to(draft_dir)}"
                        compress = zipfile.ZIP_STORED if file.suffix.lower() in video_suffixes else zipfile.ZIP_DEFLATED
                        zf.write(file, arcname, compress_type=compress)

            return zip_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def export_episode_draft_to_directory_with_summary(
        self,
        project_name: str,
        episode: int,
        draft_path: str,
        *,
        use_draft_info_name: bool = True,
    ) -> JianyingDraftExportResult:
        """
        直接在剪映草稿目录中创建草稿目录，并返回已导出 / 跳过项目摘要。

        Returns:
            草稿目录路径和导出摘要
        """
        project = self.pm.load_project(project_name)
        draft_root = Path(draft_path).expanduser()
        draft_root.mkdir(parents=True, exist_ok=True)
        _, draft_name = self._unique_draft_dir(
            draft_root,
            self._safe_draft_name(project, project_name, episode),
        )
        tmp_dir, draft_dir, _, summary = self._prepare_episode_draft_dir(
            project_name,
            episode,
            str(draft_root),
            draft_name=draft_name,
            use_draft_info_name=use_draft_info_name,
        )
        target_dir = draft_root / draft_name
        try:
            shutil.move(str(draft_dir), str(target_dir))
            return JianyingDraftExportResult(path=target_dir, summary=summary)
        except Exception:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def export_episode_draft_to_directory(
        self,
        project_name: str,
        episode: int,
        draft_path: str,
        *,
        use_draft_info_name: bool = True,
    ) -> Path:
        """
        直接在剪映草稿目录中创建草稿目录，不再生成 ZIP。

        Returns:
            已创建的剪映草稿目录路径
        """
        return self.export_episode_draft_to_directory_with_summary(
            project_name,
            episode,
            draft_path,
            use_draft_info_name=use_draft_info_name,
        ).path
