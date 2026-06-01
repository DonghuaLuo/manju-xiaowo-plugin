"""Workspace asset archive export service."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, update

from lib.app_data_dir import app_data_dir
from lib.db import async_session_factory
from lib.db.base import DEFAULT_USER_ID
from lib.db.models.agent_credential import AgentAnthropicCredential
from lib.db.models.api_key import ApiKey
from lib.db.models.asset import Asset
from lib.db.models.config import ProviderConfig, SystemSetting
from lib.db.models.credential import ProviderCredential
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from server.services.project_archive import ProjectArchiveValidationError

ASSET_ARCHIVE_FORMAT_VERSION = 1
ASSET_ARCHIVE_MANIFEST_NAME = "arcreel-assets-export.json"
ASSET_LIBRARY_METADATA_NAME = "asset-library/assets.json"
GLOBAL_CONFIG_NAME = "global_config/config.json"
PROJECTS_ROOT_NAME = "projects-root.txt"
PROJECT_ARCHIVE_MANIFEST_NAME = "arcreel-export.json"
PROJECT_FILE_NAME = "project.json"
UNSUPPORTED_ARCHIVE_DETAIL = "不是当前需要的压缩包"
LEGACY_SYSTEM_CONFIG_PARTS = ("global_config", "legacy", ".system_config.json")

ASSET_TYPES = ("character", "scene", "prop")
STORED_ARCHIVE_SUFFIXES = frozenset(
    {
        ".apng",
        ".avi",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".png",
        ".webm",
        ".webp",
        ".zip",
    }
)


@dataclass(frozen=True)
class AssetArchiveOptions:
    asset_types: tuple[str, ...]
    include_style_favorites: bool
    include_global_config: bool


@dataclass(frozen=True)
class AssetArchiveMember:
    info: zipfile.ZipInfo
    parts: tuple[str, ...]
    is_dir: bool


@dataclass(frozen=True)
class ImportArchiveDetection:
    kind: Literal["asset_archive", "project", "unsupported"]
    root_parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetArchiveImportResult:
    summary: dict[str, Any]
    warnings: list[str]
    diagnostics: dict[str, list[dict[str, Any]]]


def normalize_asset_archive_options(params: dict[str, Any] | None = None) -> AssetArchiveOptions:
    payload = params or {}
    raw_assets = payload.get("includeAssets")
    include_assets = raw_assets if isinstance(raw_assets, dict) else {}

    selected_types = tuple(
        asset_type
        for asset_type in ASSET_TYPES
        if include_assets.get(asset_type, True) is not False
    )
    include_style_favorites = include_assets.get("styleFavorites", True) is not False
    include_global_config = bool(payload.get("includeGlobalConfig"))

    if not selected_types and not include_style_favorites and not include_global_config:
        raise ValueError("至少选择一类要导出的资产或配置")

    return AssetArchiveOptions(
        asset_types=selected_types,
        include_style_favorites=include_style_favorites,
        include_global_config=include_global_config,
    )


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _iso(getattr(row, field)) for field in fields}


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _diagnostic(code: str, message: str, *, location: str | None = None) -> dict[str, str]:
    payload = {"code": code, "message": message}
    if location:
        payload["location"] = location
    return payload


def _is_hidden_member(parts: tuple[str, ...]) -> bool:
    return any(part.startswith(".") or part == "__MACOSX" for part in parts)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _text(value).strip()
    return text or None


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _dict_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _scan_archive_members(archive: zipfile.ZipFile) -> list[AssetArchiveMember]:
    members: list[AssetArchiveMember] = []
    for info in archive.infolist():
        if info.flag_bits & 0x1:
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"ZIP 包含加密条目，无法导入: {info.filename}"],
            )

        normalized_name = info.filename.replace("\\", "/")
        if normalized_name.startswith("/"):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"ZIP 包含绝对路径条目: {info.filename}"],
            )

        stripped_name = normalized_name.strip("/")
        if not stripped_name:
            continue

        parts = tuple(part for part in stripped_name.split("/") if part)
        if parts and len(parts[0]) == 2 and parts[0][1] == ":":
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"ZIP 包含绝对路径条目: {info.filename}"],
            )
        if any(part == ".." for part in parts):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"ZIP 包含路径穿越条目: {info.filename}"],
            )

        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"ZIP 包含符号链接条目: {info.filename}"],
            )

        members.append(
            AssetArchiveMember(
                info=info,
                parts=parts,
                is_dir=info.is_dir() or normalized_name.endswith("/"),
            )
        )
    return members


def detect_import_archive_kind(archive_path: Path) -> ImportArchiveDetection:
    """Classify an uploaded ZIP before importing it."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _scan_archive_members(archive)
    except zipfile.BadZipFile as exc:
        raise ProjectArchiveValidationError(
            "上传文件不是有效的 ZIP 归档",
            errors=[str(exc)],
        ) from exc

    visible_members = [member for member in members if not _is_hidden_member(member.parts)]
    asset_manifest_members = [
        member for member in visible_members if member.parts[-1] == ASSET_ARCHIVE_MANIFEST_NAME
    ]
    project_markers = [
        member
        for member in visible_members
        if member.parts[-1] in {PROJECT_ARCHIVE_MANIFEST_NAME, PROJECT_FILE_NAME}
    ]

    if asset_manifest_members and project_markers:
        raise ProjectArchiveValidationError(
            "导入包校验失败",
            errors=["ZIP 同时包含项目导出和全局资产导出标识，无法确定导入类型"],
        )

    if asset_manifest_members:
        root_candidates = {member.parts[:-1] for member in asset_manifest_members}
        if len(root_candidates) != 1:
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=["ZIP 中包含多个 arcreel-assets-export.json，无法确定全局资产包根目录"],
            )
        return ImportArchiveDetection(kind="asset_archive", root_parts=next(iter(root_candidates)))

    if project_markers:
        return ImportArchiveDetection(kind="project")

    return ImportArchiveDetection(kind="unsupported")


class AssetArchiveService:
    def __init__(self, projects_root: Path | None = None):
        self.projects_root = Path(projects_root or app_data_dir()).resolve()
        self.global_assets_root = self.projects_root / "_global_assets"
        self.style_favorites_root = self.projects_root / "_style_favorites"

    def get_export_info(self) -> dict[str, str]:
        return {
            "projectsRoot": str(self.projects_root),
            "globalAssetsRoot": str(self.global_assets_root),
            "styleFavoritesRoot": str(self.style_favorites_root),
        }

    async def import_archive(self, archive_path: Path) -> AssetArchiveImportResult:
        try:
            with tempfile.TemporaryDirectory(prefix="arcreel-assets-import-") as temp_dir:
                staging_dir = Path(temp_dir) / "assets"
                staging_dir.mkdir(parents=True, exist_ok=True)
                manifest, warnings, asset_rows, global_config = await asyncio.to_thread(
                    self._prepare_import_staging,
                    archive_path,
                    staging_dir,
                )

                summary: dict[str, Any] = {
                    "manifest": {
                        "format_version": manifest.get("format_version"),
                        "exported_at": manifest.get("exported_at"),
                    },
                    "assets": 0,
                    "asset_files": 0,
                    "style_favorites_files": 0,
                    "global_config": False,
                    "global_config_rows": {},
                    "global_config_files": 0,
                }

                async with async_session_factory() as session:
                    if asset_rows:
                        summary["assets"] = await self._import_asset_rows(session, asset_rows, warnings)
                    if global_config:
                        summary["global_config_rows"] = await self._import_global_config(
                            session,
                            global_config,
                            warnings,
                        )

                    summary.update(
                        await asyncio.to_thread(
                            self._install_imported_files,
                            staging_dir,
                        )
                    )
                    summary["global_config"] = bool(
                        summary["global_config_rows"] or summary["global_config_files"]
                    )

                    await session.commit()

                diagnostics = {
                    "auto_fixed": [],
                    "warnings": [
                        _diagnostic("asset_archive_warning", warning)
                        for warning in warnings
                    ],
                }
                return AssetArchiveImportResult(
                    summary=summary,
                    warnings=warnings,
                    diagnostics=diagnostics,
                )
        except zipfile.BadZipFile as exc:
            raise ProjectArchiveValidationError(
                "上传文件不是有效的 ZIP 归档",
                errors=[str(exc)],
            ) from exc

    def _prepare_import_staging(
        self,
        archive_path: Path,
        staging_dir: Path,
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], dict[str, Any] | None]:
        with zipfile.ZipFile(archive_path) as archive:
            members = _scan_archive_members(archive)
            root_parts, manifest = self._locate_asset_archive_root(archive, members)
            warnings = self._extract_asset_archive(archive, members, root_parts, staging_dir)

        asset_rows = self._load_asset_metadata(staging_dir, warnings)
        global_config = self._load_global_config(staging_dir, warnings)
        return manifest, warnings, asset_rows, global_config

    async def build_archive_payload(self, options: AssetArchiveOptions) -> dict[str, Any]:
        assets: list[dict[str, Any]] = []
        global_config: dict[str, Any] | None = None

        async with async_session_factory() as session:
            if options.asset_types:
                result = await session.execute(
                    select(Asset)
                    .where(Asset.type.in_(options.asset_types))
                    .order_by(Asset.type, Asset.name)
                )
                assets = [
                    _row_dict(
                        asset,
                        (
                            "id",
                            "type",
                            "name",
                            "description",
                            "voice_style",
                            "image_path",
                            "source_project",
                            "created_at",
                            "updated_at",
                        ),
                    )
                    for asset in result.scalars()
                ]

            if options.include_global_config:
                global_config = await self._collect_global_config(session)

        return {
            "assets": assets,
            "global_config": global_config,
        }

    async def _collect_global_config(self, session: Any) -> dict[str, Any]:
        provider_rows = (
            await session.execute(select(ProviderConfig).order_by(ProviderConfig.provider, ProviderConfig.key))
        ).scalars()
        setting_rows = (await session.execute(select(SystemSetting).order_by(SystemSetting.key))).scalars()
        agent_rows = (
            await session.execute(select(AgentAnthropicCredential).order_by(AgentAnthropicCredential.id))
        ).scalars()
        credential_rows = (
            await session.execute(select(ProviderCredential).order_by(ProviderCredential.provider, ProviderCredential.id))
        ).scalars()
        custom_provider_rows = (
            await session.execute(select(CustomProvider).order_by(CustomProvider.id))
        ).scalars()
        custom_model_rows = (
            await session.execute(
                select(CustomProviderModel).order_by(CustomProviderModel.provider_id, CustomProviderModel.id)
            )
        ).scalars()
        api_key_rows = (await session.execute(select(ApiKey).order_by(ApiKey.id))).scalars()

        return {
            "schema_version": 1,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "system_settings": [
                _row_dict(row, ("id", "key", "value", "updated_at"))
                for row in setting_rows
            ],
            "provider_config": [
                _row_dict(row, ("id", "provider", "key", "value", "is_secret", "updated_at"))
                for row in provider_rows
            ],
            "provider_credentials": [
                _row_dict(
                    row,
                    (
                        "id",
                        "provider",
                        "name",
                        "api_key",
                        "credentials_path",
                        "base_url",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in credential_rows
            ],
            "agent_anthropic_credentials": [
                _row_dict(
                    row,
                    (
                        "id",
                        "user_id",
                        "preset_id",
                        "display_name",
                        "base_url",
                        "api_key",
                        "model",
                        "haiku_model",
                        "sonnet_model",
                        "opus_model",
                        "subagent_model",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in agent_rows
            ],
            "custom_providers": [
                _row_dict(
                    row,
                    (
                        "id",
                        "display_name",
                        "discovery_format",
                        "base_url",
                        "api_key",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in custom_provider_rows
            ],
            "custom_provider_models": [
                _row_dict(
                    row,
                    (
                        "id",
                        "provider_id",
                        "model_id",
                        "display_name",
                        "endpoint",
                        "is_default",
                        "is_enabled",
                        "price_unit",
                        "price_input",
                        "price_output",
                        "currency",
                        "supported_durations",
                        "resolution",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in custom_model_rows
            ],
            "api_keys": [
                _row_dict(
                    row,
                    (
                        "id",
                        "user_id",
                        "name",
                        "key_hash",
                        "key_prefix",
                        "expires_at",
                        "last_used_at",
                        "created_at",
                        "updated_at",
                    ),
                )
                for row in api_key_rows
            ],
        }

    def export_to_path(
        self,
        target_path: Path,
        *,
        options: AssetArchiveOptions,
        payload: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        if target_path.exists() and target_path.is_dir():
            raise IsADirectoryError(f"导出目标不能是目录: {target_path}")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=str(target_path.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_path_str)
        try:
            summary = self._write_archive(tmp_path, options=options, payload=payload)
            os.replace(tmp_path, target_path)
            return target_path, summary
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _write_archive(
        self,
        archive_path: Path,
        *,
        options: AssetArchiveOptions,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        summary = {
            "assets": len(payload.get("assets") or []),
            "files": 0,
            "asset_types": list(options.asset_types),
            "style_favorites": options.include_style_favorites,
            "global_config": options.include_global_config,
        }
        manifest = {
            "format_version": ASSET_ARCHIVE_FORMAT_VERSION,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "projects_root": str(self.projects_root),
            "asset_types": list(options.asset_types),
            "include_style_favorites": options.include_style_favorites,
            "include_global_config": options.include_global_config,
        }

        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(ASSET_ARCHIVE_MANIFEST_NAME, _json_bytes(manifest))
            archive.writestr(PROJECTS_ROOT_NAME, f"{self.projects_root}\n")
            archive.writestr(ASSET_LIBRARY_METADATA_NAME, _json_bytes({"assets": payload.get("assets") or []}))

            for asset_type in options.asset_types:
                source = self.global_assets_root / asset_type
                summary["files"] += self._write_tree(
                    archive,
                    source,
                    Path("_global_assets") / asset_type,
                )

            if options.include_style_favorites:
                if self.style_favorites_root.exists():
                    summary["files"] += self._write_tree(
                        archive,
                        self.style_favorites_root,
                        Path("_style_favorites"),
                    )
                else:
                    archive.writestr("_style_favorites/templates.json", _json_bytes({"templates": []}))

            if options.include_global_config:
                archive.writestr(GLOBAL_CONFIG_NAME, _json_bytes(payload.get("global_config") or {}))
                summary["files"] += self._write_optional_global_config_files(archive)

        return summary

    def _locate_asset_archive_root(
        self,
        archive: zipfile.ZipFile,
        members: list[AssetArchiveMember],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        visible_members = [member for member in members if not _is_hidden_member(member.parts)]
        manifest_members = [
            member for member in visible_members if member.parts[-1] == ASSET_ARCHIVE_MANIFEST_NAME
        ]
        if not manifest_members:
            raise ProjectArchiveValidationError(
                UNSUPPORTED_ARCHIVE_DETAIL,
                errors=["请选择项目导出 ZIP，或通过“导出资产”生成的全局资产 ZIP。"],
            )

        root_candidates = {member.parts[:-1] for member in manifest_members}
        if len(root_candidates) != 1:
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=["ZIP 中包含多个 arcreel-assets-export.json，无法确定全局资产包根目录"],
            )

        manifest = self._load_member_json(
            archive,
            manifest_members[0],
            ASSET_ARCHIVE_MANIFEST_NAME,
        )
        if not isinstance(manifest.get("format_version"), int):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=["全局资产包 manifest 缺少 format_version"],
            )
        return next(iter(root_candidates)), manifest

    def _extract_asset_archive(
        self,
        archive: zipfile.ZipFile,
        members: list[AssetArchiveMember],
        root_parts: tuple[str, ...],
        staging_dir: Path,
    ) -> list[str]:
        warnings: list[str] = []
        staging_root = staging_dir.resolve()
        root_length = len(root_parts)
        allowed_roots = {
            ASSET_ARCHIVE_MANIFEST_NAME,
            ASSET_LIBRARY_METADATA_NAME.split("/", 1)[0],
            GLOBAL_CONFIG_NAME.split("/", 1)[0],
            PROJECTS_ROOT_NAME,
            "_global_assets",
            "_style_favorites",
        }
        skipped_roots: set[str] = set()

        for member in members:
            if member.parts[:root_length] != root_parts:
                continue

            relative_parts = member.parts[root_length:]
            if not relative_parts:
                continue
            if relative_parts == (ASSET_ARCHIVE_MANIFEST_NAME,):
                continue
            if _is_hidden_member(relative_parts) and relative_parts != LEGACY_SYSTEM_CONFIG_PARTS:
                continue

            if relative_parts[0] not in allowed_roots:
                if relative_parts[0] not in skipped_roots:
                    skipped_roots.add(relative_parts[0])
                    warnings.append(f"全局资产包包含未识别条目 '{relative_parts[0]}'，已跳过")
                continue

            target_path = staging_dir.joinpath(*relative_parts)
            try:
                target_path.resolve(strict=False).relative_to(staging_root)
            except ValueError as exc:
                raise ProjectArchiveValidationError(
                    "导入包校验失败",
                    errors=[f"解压路径越界: {'/'.join(member.parts)}"],
                ) from exc

            if member.is_dir:
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member.info) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)

        return warnings

    @staticmethod
    def _load_member_json(
        archive: zipfile.ZipFile,
        member: AssetArchiveMember,
        label: str,
    ) -> dict[str, Any]:
        try:
            with archive.open(member.info) as handle:
                payload = json.loads(handle.read().decode("utf-8"))
        except Exception as exc:
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"无法解析 {label}: {'/'.join(member.parts)}"],
            ) from exc
        if not isinstance(payload, dict):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"{label} 必须是 JSON 对象"],
            )
        return payload

    @staticmethod
    def _read_json_file(path: Path, label: str) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"无法解析 {label}: {path.as_posix()}"],
            ) from exc
        if not isinstance(payload, dict):
            raise ProjectArchiveValidationError(
                "导入包校验失败",
                errors=[f"{label} 必须是 JSON 对象"],
            )
        return payload

    def _load_asset_metadata(self, staging_dir: Path, warnings: list[str]) -> list[dict[str, Any]]:
        payload = self._read_json_file(staging_dir / ASSET_LIBRARY_METADATA_NAME, ASSET_LIBRARY_METADATA_NAME)
        if not payload:
            return []
        rows = payload.get("assets")
        if not isinstance(rows, list):
            warnings.append("asset-library/assets.json 中 assets 字段不是列表，已跳过资产元数据")
            return []
        result: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                warnings.append(f"asset-library/assets.json 第 {index + 1} 条不是对象，已跳过")
                continue
            asset_type = _text(row.get("type")).strip()
            name = _text(row.get("name")).strip()
            if asset_type not in ASSET_TYPES or not name:
                warnings.append(f"asset-library/assets.json 第 {index + 1} 条资产类型或名称无效，已跳过")
                continue
            result.append(row)
        return result

    def _load_global_config(self, staging_dir: Path, warnings: list[str]) -> dict[str, Any] | None:
        payload = self._read_json_file(staging_dir / GLOBAL_CONFIG_NAME, GLOBAL_CONFIG_NAME)
        if not payload:
            return None
        if payload.get("schema_version") not in (None, 1):
            warnings.append("global_config/config.json schema_version 不是当前版本，已按兼容模式导入")
        return payload

    async def _import_asset_rows(
        self,
        session: Any,
        rows: list[dict[str, Any]],
        warnings: list[str],
    ) -> int:
        imported = 0
        for row in rows:
            asset_type = _text(row.get("type")).strip()
            name = _text(row.get("name")).strip()
            if asset_type not in ASSET_TYPES or not name:
                continue

            existing = (
                await session.execute(select(Asset).where(Asset.type == asset_type, Asset.name == name))
            ).scalar_one_or_none()
            asset_id = _text(row.get("id")).strip()
            if existing is None and asset_id:
                existing = (await session.execute(select(Asset).where(Asset.id == asset_id))).scalar_one_or_none()

            fields = {
                "type": asset_type,
                "name": name,
                "description": _text(row.get("description")),
                "voice_style": _text(row.get("voice_style")),
                "image_path": _nullable_text(row.get("image_path")),
                "source_project": _nullable_text(row.get("source_project")),
            }
            if existing is None:
                session.add(Asset(id=asset_id or str(uuid.uuid4()), **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
            imported += 1

        try:
            await session.flush()
        except Exception:
            warnings.append("资产元数据导入失败，可能存在重复资产 ID 或名称")
            raise
        return imported

    async def _import_global_config(
        self,
        session: Any,
        payload: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, int]:
        provider_id_map: dict[int, int] = {}
        summary = {
            "system_settings": await self._import_system_settings(session, _dict_rows(payload, "system_settings")),
            "provider_config": await self._import_provider_config(session, _dict_rows(payload, "provider_config")),
            "provider_credentials": await self._import_provider_credentials(
                session,
                _dict_rows(payload, "provider_credentials"),
            ),
            "agent_anthropic_credentials": await self._import_agent_credentials(
                session,
                _dict_rows(payload, "agent_anthropic_credentials"),
            ),
            "custom_providers": await self._import_custom_providers(
                session,
                _dict_rows(payload, "custom_providers"),
                provider_id_map,
            ),
            "custom_provider_models": await self._import_custom_provider_models(
                session,
                _dict_rows(payload, "custom_provider_models"),
                provider_id_map,
                warnings,
            ),
            "api_keys": await self._import_api_keys(session, _dict_rows(payload, "api_keys")),
        }
        await session.flush()
        return summary

    async def _import_system_settings(self, session: Any, rows: list[dict[str, Any]]) -> int:
        imported = 0
        for row in rows:
            key = _text(row.get("key")).strip()
            if not key:
                continue
            existing = (
                await session.execute(select(SystemSetting).where(SystemSetting.key == key))
            ).scalar_one_or_none()
            value = _text(row.get("value"))
            if existing is None:
                session.add(SystemSetting(key=key, value=value))
            else:
                existing.value = value
            imported += 1
        return imported

    async def _import_provider_config(self, session: Any, rows: list[dict[str, Any]]) -> int:
        imported = 0
        for row in rows:
            provider = _text(row.get("provider")).strip()
            key = _text(row.get("key")).strip()
            if not provider or not key:
                continue
            existing = (
                await session.execute(
                    select(ProviderConfig).where(ProviderConfig.provider == provider, ProviderConfig.key == key)
                )
            ).scalar_one_or_none()
            fields = {
                "provider": provider,
                "key": key,
                "value": _text(row.get("value")),
                "is_secret": _bool(row.get("is_secret")),
            }
            if existing is None:
                session.add(ProviderConfig(**fields))
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            imported += 1
        return imported

    async def _import_provider_credentials(self, session: Any, rows: list[dict[str, Any]]) -> int:
        imported = 0
        for row in rows:
            provider = _text(row.get("provider")).strip()
            name = _text(row.get("name")).strip() or "Imported"
            if not provider:
                continue
            is_active = _bool(row.get("is_active"))
            if is_active:
                await session.execute(
                    update(ProviderCredential).where(ProviderCredential.provider == provider).values(is_active=False)
                )
            existing = (
                await session.execute(
                    select(ProviderCredential).where(
                        ProviderCredential.provider == provider,
                        ProviderCredential.name == name,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "provider": provider,
                "name": name,
                "api_key": _nullable_text(row.get("api_key")),
                "credentials_path": _nullable_text(row.get("credentials_path")),
                "base_url": _nullable_text(row.get("base_url")),
                "is_active": is_active,
            }
            if existing is None:
                session.add(ProviderCredential(**fields))
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            imported += 1
        return imported

    async def _import_agent_credentials(self, session: Any, rows: list[dict[str, Any]]) -> int:
        imported = 0
        for row in rows:
            user_id = _text(row.get("user_id")).strip() or DEFAULT_USER_ID
            preset_id = _text(row.get("preset_id")).strip() or "__custom__"
            display_name = _text(row.get("display_name")).strip() or preset_id
            is_active = _bool(row.get("is_active"))
            if is_active:
                await session.execute(
                    update(AgentAnthropicCredential)
                    .where(AgentAnthropicCredential.user_id == user_id)
                    .values(is_active=False)
                )
            existing = (
                await session.execute(
                    select(AgentAnthropicCredential).where(
                        AgentAnthropicCredential.user_id == user_id,
                        AgentAnthropicCredential.preset_id == preset_id,
                        AgentAnthropicCredential.display_name == display_name,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "user_id": user_id,
                "preset_id": preset_id,
                "display_name": display_name,
                "base_url": _text(row.get("base_url")),
                "api_key": _text(row.get("api_key")),
                "model": _nullable_text(row.get("model")),
                "haiku_model": _nullable_text(row.get("haiku_model")),
                "sonnet_model": _nullable_text(row.get("sonnet_model")),
                "opus_model": _nullable_text(row.get("opus_model")),
                "subagent_model": _nullable_text(row.get("subagent_model")),
                "is_active": is_active,
            }
            if existing is None:
                session.add(AgentAnthropicCredential(**fields))
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            imported += 1
        return imported

    async def _import_custom_providers(
        self,
        session: Any,
        rows: list[dict[str, Any]],
        provider_id_map: dict[int, int],
    ) -> int:
        imported = 0
        for row in rows:
            display_name = _text(row.get("display_name")).strip()
            base_url = _text(row.get("base_url")).strip()
            if not display_name:
                continue
            existing = (
                await session.execute(
                    select(CustomProvider).where(
                        CustomProvider.display_name == display_name,
                        CustomProvider.base_url == base_url,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "display_name": display_name,
                "discovery_format": _text(row.get("discovery_format")).strip() or "openai",
                "base_url": base_url,
                "api_key": _text(row.get("api_key")),
            }
            if existing is None:
                existing = CustomProvider(**fields)
                session.add(existing)
                await session.flush()
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            old_id = _int_or_none(row.get("id"))
            if old_id is not None and existing.id is not None:
                provider_id_map[old_id] = existing.id
            imported += 1
        return imported

    async def _import_custom_provider_models(
        self,
        session: Any,
        rows: list[dict[str, Any]],
        provider_id_map: dict[int, int],
        warnings: list[str],
    ) -> int:
        imported = 0
        for row in rows:
            old_provider_id = _int_or_none(row.get("provider_id"))
            target_provider_id = provider_id_map.get(old_provider_id) if old_provider_id is not None else None
            model_id = _text(row.get("model_id")).strip()
            if target_provider_id is None or not model_id:
                warnings.append(f"自定义供应商模型 '{model_id or '<unknown>'}' 缺少可匹配的供应商，已跳过")
                continue
            existing = (
                await session.execute(
                    select(CustomProviderModel).where(
                        CustomProviderModel.provider_id == target_provider_id,
                        CustomProviderModel.model_id == model_id,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "provider_id": target_provider_id,
                "model_id": model_id,
                "display_name": _text(row.get("display_name")).strip() or model_id,
                "endpoint": _text(row.get("endpoint")).strip() or "text",
                "is_default": _bool(row.get("is_default")),
                "is_enabled": _bool(row.get("is_enabled"), True),
                "price_unit": _nullable_text(row.get("price_unit")),
                "price_input": _float_or_none(row.get("price_input")),
                "price_output": _float_or_none(row.get("price_output")),
                "currency": _nullable_text(row.get("currency")),
                "supported_durations": _nullable_text(row.get("supported_durations")),
                "resolution": _nullable_text(row.get("resolution")),
            }
            if existing is None:
                session.add(CustomProviderModel(**fields))
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            imported += 1
        return imported

    async def _import_api_keys(self, session: Any, rows: list[dict[str, Any]]) -> int:
        imported = 0
        for row in rows:
            name = _text(row.get("name")).strip()
            key_hash = _text(row.get("key_hash")).strip()
            key_prefix = _text(row.get("key_prefix")).strip()
            if not name or not key_hash or not key_prefix:
                continue
            existing = (
                await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
            ).scalar_one_or_none()
            if existing is None:
                existing = (await session.execute(select(ApiKey).where(ApiKey.name == name))).scalar_one_or_none()
            fields = {
                "user_id": _text(row.get("user_id")).strip() or DEFAULT_USER_ID,
                "name": name,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "expires_at": _datetime_or_none(row.get("expires_at")),
                "last_used_at": _datetime_or_none(row.get("last_used_at")),
            }
            if existing is None:
                session.add(ApiKey(**fields))
            else:
                for field_name, value in fields.items():
                    setattr(existing, field_name, value)
            imported += 1
        return imported

    def _install_asset_files(self, staging_dir: Path) -> int:
        written = 0
        for asset_type in ASSET_TYPES:
            written += self._copy_tree(
                staging_dir / "_global_assets" / asset_type,
                self.global_assets_root / asset_type,
            )
        return written

    def _install_style_favorites(self, staging_dir: Path) -> int:
        return self._copy_tree(staging_dir / "_style_favorites", self.style_favorites_root)

    def _install_global_config_files(self, staging_dir: Path) -> int:
        written = 0
        legacy_config = staging_dir / "global_config" / "legacy" / ".system_config.json"
        if legacy_config.exists() and legacy_config.is_file() and not legacy_config.is_symlink():
            target = self.projects_root / ".system_config.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_config, target)
            written += 1

        written += self._copy_tree(
            staging_dir / "global_config" / "vertex_keys",
            self.projects_root.parent / "vertex_keys",
        )
        return written

    def _install_imported_files(self, staging_dir: Path) -> dict[str, int]:
        return {
            "asset_files": self._install_asset_files(staging_dir),
            "style_favorites_files": self._install_style_favorites(staging_dir),
            "global_config_files": self._install_global_config_files(staging_dir),
        }

    @staticmethod
    def _copy_tree(source_root: Path, target_root: Path) -> int:
        if not source_root.exists() or not source_root.is_dir() or source_root.is_symlink():
            return 0

        written = 0
        target_root.mkdir(parents=True, exist_ok=True)
        target_base = target_root.resolve(strict=False)

        for current_dir, dirnames, filenames in os.walk(source_root):
            current_path = Path(current_dir)
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if not name.startswith(".") and not (current_path / name).is_symlink()
            ]
            relative_dir = current_path.relative_to(source_root)
            target_dir = target_root / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            for filename in sorted(filenames):
                source_path = current_path / filename
                if filename.startswith(".") or source_path.is_symlink() or not source_path.is_file():
                    continue
                target_path = target_dir / filename
                try:
                    target_path.resolve(strict=False).relative_to(target_base)
                except ValueError as exc:
                    raise ProjectArchiveValidationError(
                        "导入包校验失败",
                        errors=[f"安装路径越界: {target_path}"],
                    ) from exc
                shutil.copy2(source_path, target_path)
                written += 1

        return written

    def _write_optional_global_config_files(self, archive: zipfile.ZipFile) -> int:
        written = 0
        legacy_system_config = self.projects_root / ".system_config.json"
        if legacy_system_config.exists() and legacy_system_config.is_file() and not legacy_system_config.is_symlink():
            archive.write(
                legacy_system_config,
                arcname="global_config/legacy/.system_config.json",
                compress_type=self._archive_compression_type(legacy_system_config),
            )
            written += 1

        vertex_keys_root = self.projects_root.parent / "vertex_keys"
        if vertex_keys_root.exists():
            written += self._write_tree(archive, vertex_keys_root, Path("global_config/vertex_keys"))
        return written

    def _write_tree(self, archive: zipfile.ZipFile, source_root: Path, archive_root: Path) -> int:
        if not source_root.exists() or not source_root.is_dir() or source_root.is_symlink():
            return 0

        written = 0
        self._write_directory_entry(archive, archive_root.parts)
        for current_dir, dirnames, filenames in os.walk(source_root):
            current_path = Path(current_dir)
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if not name.startswith(".") and not (current_path / name).is_symlink()
            ]
            relative_dir = current_path.relative_to(source_root)
            if relative_dir != Path("."):
                self._write_directory_entry(archive, (*archive_root.parts, *relative_dir.parts))

            for filename in sorted(filenames):
                source_path = current_path / filename
                if filename.startswith(".") or source_path.is_symlink() or not source_path.is_file():
                    continue
                archive_name = (archive_root / relative_dir / filename).as_posix()
                archive.write(
                    source_path,
                    arcname=archive_name,
                    compress_type=self._archive_compression_type(source_path),
                )
                written += 1
        return written

    @staticmethod
    def _write_directory_entry(archive: zipfile.ZipFile, parts: tuple[str, ...]) -> None:
        dirname = "/".join(parts).rstrip("/") + "/"
        info = zipfile.ZipInfo(dirname)
        info.external_attr = (0o40755 & 0xFFFF) << 16
        archive.writestr(info, b"")

    @staticmethod
    def _archive_compression_type(source_path: Path) -> int:
        if source_path.suffix.lower() in STORED_ARCHIVE_SUFFIXES:
            return zipfile.ZIP_STORED
        return zipfile.ZIP_DEFLATED
