#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""manju direct IPC API registration for Xiaowo plugin frontend calls."""

from __future__ import annotations

from typing import Any


MANJU_API_COMMANDS = (
    "manju_api_activate_agent_credential",
    "manju_api_activate_credential",
    "manju_api_add_asset_from_project",
    "manju_api_add_character",
    "manju_api_add_project_prop",
    "manju_api_add_project_scene",
    "manju_api_add_reference_video_unit",
    "manju_api_analyze_style_image",
    "manju_api_answer_assistant_question",
    "manju_api_apply_assets_to_project",
    "manju_api_cancel_all_preview",
    "manju_api_cancel_all_queued",
    "manju_api_cancel_preview",
    "manju_api_cancel_task",
    "manju_api_change_script_splitting_template",
    "manju_api_create_agent_credential",
    "manju_api_create_asset",
    "manju_api_create_credential",
    "manju_api_create_custom_provider",
    "manju_api_create_favorite_style_template",
    "manju_api_create_project",
    "manju_api_delete_agent_credential",
    "manju_api_delete_asset",
    "manju_api_delete_assistant_session",
    "manju_api_delete_character",
    "manju_api_delete_credential",
    "manju_api_delete_custom_provider",
    "manju_api_delete_design_resource",
    "manju_api_delete_draft",
    "manju_api_delete_favorite_style_template",
    "manju_api_delete_project",
    "manju_api_delete_project_prop",
    "manju_api_delete_project_scene",
    "manju_api_delete_reference_video_unit",
    "manju_api_delete_script_splitting_template",
    "manju_api_delete_source_file",
    "manju_api_delete_version",
    "manju_api_detect_jianying_draft_root",
    "manju_api_discover_anthropic_models",
    "manju_api_discover_models",
    "manju_api_discover_models_for_provider",
    "manju_api_event_poll",
    "manju_api_event_subscribe",
    "manju_api_export_script_splitting_template",
    "manju_api_finalize_episode",
    "manju_api_full_update_custom_provider",
    "manju_api_generate_character",
    "manju_api_generate_grid",
    "manju_api_generate_overview",
    "manju_api_generate_project_prop",
    "manju_api_generate_project_scene",
    "manju_api_generate_reference_video_unit",
    "manju_api_generate_storyboard",
    "manju_api_generate_video",
    "manju_api_get_asset",
    "manju_api_get_asset_archive_export_info",
    "manju_api_get_asset_roots",
    "manju_api_get_assistant_session",
    "manju_api_get_assistant_snapshot",
    "manju_api_get_cost_estimate",
    "manju_api_get_custom_provider",
    "manju_api_get_custom_provider_credentials",
    "manju_api_get_design_resource_usage",
    "manju_api_get_draft_content",
    "manju_api_get_export_task_status",
    "manju_api_get_external_generation_package",
    "manju_api_get_finalization_report",
    "manju_api_get_grid",
    "manju_api_get_project",
    "manju_api_get_provider_config",
    "manju_api_get_provider_recommendations",
    "manju_api_get_providers",
    "manju_api_get_quality_analysis",
    "manju_api_get_quality_ratings",
    "manju_api_get_quality_stats",
    "manju_api_get_script",
    "manju_api_get_script_splitting_templates",
    "manju_api_get_source_content",
    "manju_api_get_style_templates",
    "manju_api_get_system_config",
    "manju_api_get_task",
    "manju_api_get_task_stats",
    "manju_api_get_usage_calls",
    "manju_api_get_usage_projects",
    "manju_api_get_usage_stats",
    "manju_api_get_usage_stats_grouped",
    "manju_api_get_versions",
    "manju_api_get_video_capabilities",
    "manju_api_import_project",
    "manju_api_import_script_splitting_template",
    "manju_api_interrupt_assistant_session",
    "manju_api_list_agent_credentials",
    "manju_api_list_agent_preset_providers",
    "manju_api_list_assets",
    "manju_api_list_assistant_sessions",
    "manju_api_list_assistant_skills",
    "manju_api_list_credentials",
    "manju_api_list_custom_providers",
    "manju_api_list_drafts",
    "manju_api_list_endpoint_catalog",
    "manju_api_list_files",
    "manju_api_list_grids",
    "manju_api_list_project_tasks",
    "manju_api_list_projects",
    "manju_api_list_reference_video_units",
    "manju_api_list_tasks",
    "manju_api_open_desktop_path",
    "manju_api_patch_provider_config",
    "manju_api_patch_reference_video_unit",
    "manju_api_preview_generation_routes",
    "manju_api_preview_script_splitting_template_change",
    "manju_api_preview_storyboard_reference_usage",
    "manju_api_probe_text_structured_output",
    "manju_api_read_local_file",
    "manju_api_regenerate_grid",
    "manju_api_reorder_reference_video_units",
    "manju_api_replace_asset_image",
    "manju_api_replace_custom_provider_models",
    "manju_api_restore_version",
    "manju_api_run_agent_ops",
    "manju_api_save_diagnostics_archive",
    "manju_api_save_draft",
    "manju_api_save_script_splitting_template",
    "manju_api_save_source_file",
    "manju_api_send_assistant_message",
    "manju_api_start_asset_archive_export",
    "manju_api_start_jianying_draft_export",
    "manju_api_start_project_archive_export",
    "manju_api_test_agent_connection_draft",
    "manju_api_test_agent_credential",
    "manju_api_test_custom_connection",
    "manju_api_test_custom_connection_by_id",
    "manju_api_test_provider_connection",
    "manju_api_update_agent_credential",
    "manju_api_update_asset",
    "manju_api_update_character",
    "manju_api_update_credential",
    "manju_api_update_custom_provider",
    "manju_api_update_overview",
    "manju_api_update_project",
    "manju_api_update_project_prop",
    "manju_api_update_project_scene",
    "manju_api_update_scene",
    "manju_api_update_segment",
    "manju_api_update_system_config",
    "manju_api_upload_external_media_version",
    "manju_api_upload_file",
    "manju_api_upload_style_image",
    "manju_api_upload_vertex_credential",
    "manju_api_upsert_quality_rating",
)


_DIRECT_ASYNC_COMMANDS = {
    "manju_api_start_project_archive_export": "start_project_archive_export",
    "manju_api_get_asset_archive_export_info": "asset_archive_export_info",
    "manju_api_start_asset_archive_export": "start_asset_archive_export",
    "manju_api_get_export_task_status": "get_export_task_status",
    "manju_api_open_desktop_path": "open_desktop_path",
    "manju_api_save_diagnostics_archive": "save_diagnostics_archive",
    "manju_api_start_jianying_draft_export": "start_jianying_draft_export",
    "manju_api_detect_jianying_draft_root": "detect_jianying_draft_root",
}


def _normalize_params(params: Any) -> dict[str, Any]:
    return params if isinstance(params, dict) else {}


def _emit_manju_api_events(sdk: Any, result: dict[str, Any]) -> dict[str, Any]:
    for event in result.get("events") or []:
        sdk.send_event("manju_api_event", event)
    return result


async def _handle_event_subscribe(params: dict[str, Any], sdk: Any) -> dict[str, Any]:
    from utils.arcreel_ipc_bridge import build_event_snapshot

    return _emit_manju_api_events(sdk, await build_event_snapshot(params))


async def _handle_event_poll(params: dict[str, Any], sdk: Any) -> dict[str, Any]:
    from utils.arcreel_ipc_bridge import poll_event_streams

    return _emit_manju_api_events(sdk, await poll_event_streams(params))


def _handle_asset_roots() -> dict[str, str]:
    from lib.app_data_dir import app_data_dir

    projects_root = app_data_dir()
    return {
        "projects_root": str(projects_root),
        "global_assets_root": str(projects_root / "_global_assets"),
    }


async def _handle_direct_async(command: str, params: dict[str, Any]) -> dict[str, Any]:
    from utils import arcreel_ipc_bridge

    handler_name = _DIRECT_ASYNC_COMMANDS[command]
    return await getattr(arcreel_ipc_bridge, handler_name)(params)


async def handle_manju_api_command(command: str, params: Any, sdk: Any) -> Any:
    payload = _normalize_params(params)

    if command == "manju_api_event_subscribe":
        return await _handle_event_subscribe(payload, sdk)
    if command == "manju_api_event_poll":
        return await _handle_event_poll(payload, sdk)
    if command == "manju_api_get_asset_roots":
        return _handle_asset_roots()
    if command == "manju_api_read_local_file":
        from utils.arcreel_ipc_bridge import read_local_file_base64

        return read_local_file_base64(payload)
    if command in _DIRECT_ASYNC_COMMANDS:
        return await _handle_direct_async(command, payload)

    from utils.arcreel_ipc_bridge import dispatch_ipc_command_request

    return await dispatch_ipc_command_request(command, payload)


def register_manju_api_handlers(sdk: Any) -> None:
    for command in MANJU_API_COMMANDS:

        async def handler(params: Any, _command: str = command) -> Any:
            return await handle_manju_api_command(_command, params, sdk)

        sdk.register(command, handler)
