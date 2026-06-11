#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Explicit Manju IPC command dispatcher.

Each frontend ``manju_api_*`` command maps to a known backend endpoint function.
The payload contains path parameters, query parameters, body data, and optional
local files.  It intentionally does not accept WebUI-style ``operation`` or
``resource`` routing fields.
"""

from __future__ import annotations

import importlib
from typing import Any


_COMMAND_ENDPOINTS: dict[str, tuple[str, str]] = {
    "manju_api_activate_agent_credential": ("server.routers.agent_config", "activate_credential"),
    "manju_api_activate_credential": ("server.routers.providers", "activate_credential"),
    "manju_api_add_asset_from_project": ("server.routers.assets", "from_project"),
    "manju_api_add_character": ("utils.manju_asset_ipc", "add_character"),
    "manju_api_add_project_prop": ("utils.manju_asset_ipc", "add_prop"),
    "manju_api_add_project_scene": ("utils.manju_asset_ipc", "add_scene"),
    "manju_api_add_reference_video_unit": ("server.routers.reference_videos", "add_unit"),
    "manju_api_analyze_style_image": ("server.routers.files", "analyze_style_image"),
    "manju_api_answer_assistant_question": ("server.routers.assistant", "answer_question"),
    "manju_api_apply_assets_to_project": ("server.routers.assets", "apply_to_project"),
    "manju_api_cancel_all_preview": ("server.routers.tasks", "cancel_all_preview"),
    "manju_api_cancel_all_queued": ("server.routers.tasks", "cancel_all_queued"),
    "manju_api_cancel_preview": ("server.routers.tasks", "cancel_preview"),
    "manju_api_cancel_task": ("server.routers.tasks", "cancel_task"),
    "manju_api_change_script_splitting_template": ("server.routers.projects", "change_script_splitting_template"),
    "manju_api_create_agent_credential": ("server.routers.agent_config", "create_credential"),
    "manju_api_create_asset": ("server.routers.assets", "create_asset"),
    "manju_api_create_credential": ("server.routers.providers", "create_credential"),
    "manju_api_create_custom_provider": ("server.routers.custom_providers", "create_provider"),
    "manju_api_create_favorite_style_template": ("server.routers.files", "create_favorite_style_template"),
    "manju_api_create_project": ("server.routers.projects", "create_project"),
    "manju_api_delete_agent_credential": ("server.routers.agent_config", "delete_credential"),
    "manju_api_delete_asset": ("server.routers.assets", "delete_asset"),
    "manju_api_delete_assistant_session": ("server.routers.assistant", "delete_session"),
    "manju_api_delete_character": ("utils.manju_asset_ipc", "delete_character"),
    "manju_api_delete_credential": ("server.routers.providers", "delete_credential"),
    "manju_api_delete_custom_provider": ("server.routers.custom_providers", "delete_provider"),
    "manju_api_delete_design_resource": ("server.routers.versions", "delete_design_resource"),
    "manju_api_delete_draft": ("server.routers.files", "delete_draft"),
    "manju_api_delete_favorite_style_template": ("server.routers.files", "delete_favorite_style_template_route"),
    "manju_api_delete_project": ("server.routers.projects", "delete_project"),
    "manju_api_delete_project_prop": ("utils.manju_asset_ipc", "delete_prop"),
    "manju_api_delete_project_scene": ("utils.manju_asset_ipc", "delete_scene"),
    "manju_api_delete_reference_video_unit": ("server.routers.reference_videos", "delete_unit"),
    "manju_api_delete_script_splitting_template": ("server.routers.projects", "delete_script_splitting_template"),
    "manju_api_delete_source_file": ("server.routers.files", "delete_source_file"),
    "manju_api_delete_version": ("server.routers.versions", "delete_version"),
    "manju_api_discover_anthropic_models": ("server.routers.custom_providers", "discover_anthropic_models_endpoint"),
    "manju_api_discover_models": ("server.routers.custom_providers", "discover_models_endpoint"),
    "manju_api_discover_models_for_provider": ("server.routers.custom_providers", "discover_models_by_id"),
    "manju_api_export_script_splitting_template": ("server.routers.projects", "export_script_splitting_template_payload"),
    "manju_api_finalize_episode": ("server.routers.generate", "finalize_episode"),
    "manju_api_full_update_custom_provider": ("server.routers.custom_providers", "full_update_provider"),
    "manju_api_generate_character": ("server.routers.generate", "generate_character"),
    "manju_api_generate_grid": ("server.routers.grids", "generate_grid"),
    "manju_api_generate_overview": ("server.routers.projects", "generate_overview"),
    "manju_api_generate_project_prop": ("server.routers.generate", "generate_prop"),
    "manju_api_generate_project_scene": ("server.routers.generate", "generate_scene"),
    "manju_api_generate_reference_video_unit": ("server.routers.reference_videos", "generate_unit"),
    "manju_api_generate_storyboard": ("server.routers.generate", "generate_storyboard"),
    "manju_api_generate_video": ("server.routers.generate", "generate_video"),
    "manju_api_get_asset": ("server.routers.assets", "get_asset"),
    "manju_api_get_assistant_session": ("server.routers.assistant", "get_session"),
    "manju_api_get_assistant_snapshot": ("server.routers.assistant", "get_snapshot"),
    "manju_api_get_cost_estimate": ("server.routers.cost_estimation", "get_cost_estimate"),
    "manju_api_get_custom_provider": ("server.routers.custom_providers", "get_provider"),
    "manju_api_get_custom_provider_credentials": ("server.routers.custom_providers", "get_provider_credentials"),
    "manju_api_get_design_resource_usage": ("server.routers.versions", "get_design_resource_usage"),
    "manju_api_get_draft_content": ("server.routers.files", "get_draft_content"),
    "manju_api_get_external_generation_package": ("server.routers.generate", "get_external_generation_package"),
    "manju_api_get_finalization_report": ("server.routers.generate", "get_finalization_report"),
    "manju_api_get_grid": ("server.routers.grids", "get_grid"),
    "manju_api_get_project": ("server.routers.projects", "get_project"),
    "manju_api_get_provider_config": ("server.routers.providers", "get_provider_config"),
    "manju_api_get_provider_recommendations": ("server.routers.usage", "get_provider_recommendations"),
    "manju_api_get_providers": ("server.routers.providers", "list_providers"),
    "manju_api_get_quality_analysis": ("server.routers.quality", "get_quality_analysis"),
    "manju_api_get_quality_ratings": ("server.routers.quality", "list_quality_ratings"),
    "manju_api_get_quality_stats": ("server.routers.quality", "get_quality_stats"),
    "manju_api_get_script": ("server.routers.projects", "get_script"),
    "manju_api_get_script_splitting_templates": ("server.routers.projects", "get_script_splitting_templates"),
    "manju_api_get_source_content": ("server.routers.files", "get_source_file"),
    "manju_api_get_style_templates": ("server.routers.projects", "get_style_templates"),
    "manju_api_get_system_config": ("server.routers.system_config", "get_system_config"),
    "manju_api_get_task": ("server.routers.tasks", "get_task"),
    "manju_api_get_task_stats": ("server.routers.tasks", "get_task_stats"),
    "manju_api_get_usage_calls": ("server.routers.usage", "get_calls"),
    "manju_api_get_usage_projects": ("server.routers.usage", "get_projects_list"),
    "manju_api_get_usage_stats": ("server.routers.usage", "get_stats"),
    "manju_api_get_usage_stats_grouped": ("server.routers.usage", "get_stats"),
    "manju_api_get_versions": ("server.routers.versions", "get_versions"),
    "manju_api_get_video_capabilities": ("server.routers.projects", "get_video_capabilities"),
    "manju_api_import_project": ("server.routers.projects", "import_project_archive"),
    "manju_api_import_script_splitting_template": ("server.routers.projects", "import_script_splitting_template"),
    "manju_api_interrupt_assistant_session": ("server.routers.assistant", "interrupt_session"),
    "manju_api_list_agent_credentials": ("server.routers.agent_config", "list_credentials"),
    "manju_api_list_agent_preset_providers": ("server.routers.agent_config", "list_preset_providers"),
    "manju_api_list_assets": ("server.routers.assets", "list_assets"),
    "manju_api_list_assistant_sessions": ("server.routers.assistant", "list_sessions"),
    "manju_api_list_assistant_skills": ("server.routers.assistant", "list_skills"),
    "manju_api_list_credentials": ("server.routers.providers", "list_credentials"),
    "manju_api_list_custom_providers": ("server.routers.custom_providers", "list_providers"),
    "manju_api_list_drafts": ("server.routers.files", "list_drafts"),
    "manju_api_list_endpoint_catalog": ("server.routers.custom_providers", "list_endpoint_catalog"),
    "manju_api_list_files": ("server.routers.files", "list_project_files"),
    "manju_api_list_grids": ("server.routers.grids", "list_grids"),
    "manju_api_list_project_tasks": ("server.routers.tasks", "list_project_tasks"),
    "manju_api_list_projects": ("server.routers.projects", "list_projects"),
    "manju_api_list_reference_video_units": ("server.routers.reference_videos", "list_units"),
    "manju_api_list_tasks": ("server.routers.tasks", "list_tasks"),
    "manju_api_patch_provider_config": ("server.routers.providers", "patch_provider_config"),
    "manju_api_patch_reference_video_unit": ("server.routers.reference_videos", "patch_unit"),
    "manju_api_preview_generation_routes": ("server.routers.generate", "preview_generation_routes"),
    "manju_api_preview_script_splitting_template_change": ("server.routers.projects", "preview_script_splitting_template_change"),
    "manju_api_preview_storyboard_reference_usage": ("server.routers.generate", "preview_storyboard_references"),
    "manju_api_probe_text_structured_output": ("server.routers.providers", "probe_text_structured_output"),
    "manju_api_regenerate_grid": ("server.routers.grids", "regenerate_grid"),
    "manju_api_reorder_reference_video_units": ("server.routers.reference_videos", "reorder_units"),
    "manju_api_replace_asset_image": ("server.routers.assets", "replace_image"),
    "manju_api_replace_custom_provider_models": ("server.routers.custom_providers", "replace_models"),
    "manju_api_restore_version": ("server.routers.versions", "restore_version"),
    "manju_api_run_agent_ops": ("utils.manju_agent_ops_ipc", "run_agent_ops"),
    "manju_api_save_draft": ("server.routers.files", "update_draft_content"),
    "manju_api_save_script_splitting_template": ("server.routers.projects", "upsert_script_splitting_template"),
    "manju_api_save_source_file": ("server.routers.files", "update_source_file"),
    "manju_api_send_assistant_message": ("server.routers.assistant", "send_message"),
    "manju_api_test_agent_connection_draft": ("server.routers.agent_config", "test_connection_draft"),
    "manju_api_test_agent_credential": ("server.routers.agent_config", "test_credential"),
    "manju_api_test_custom_connection": ("server.routers.custom_providers", "test_connection"),
    "manju_api_test_custom_connection_by_id": ("server.routers.custom_providers", "test_connection_by_id"),
    "manju_api_test_provider_connection": ("server.routers.providers", "test_provider_connection"),
    "manju_api_update_agent_credential": ("server.routers.agent_config", "update_credential"),
    "manju_api_update_asset": ("server.routers.assets", "update_asset"),
    "manju_api_update_character": ("utils.manju_asset_ipc", "update_character"),
    "manju_api_update_credential": ("server.routers.providers", "update_credential"),
    "manju_api_update_custom_provider": ("server.routers.custom_providers", "update_provider"),
    "manju_api_update_overview": ("server.routers.projects", "update_overview"),
    "manju_api_update_project": ("server.routers.projects", "update_project"),
    "manju_api_update_project_prop": ("utils.manju_asset_ipc", "update_prop"),
    "manju_api_update_project_scene": ("utils.manju_asset_ipc", "update_scene"),
    "manju_api_update_scene": ("server.routers.projects", "update_scene"),
    "manju_api_update_segment": ("server.routers.projects", "update_segment"),
    "manju_api_update_system_config": ("server.routers.system_config", "patch_system_config"),
    "manju_api_upload_external_media_version": ("server.routers.versions", "upload_external_media_version"),
    "manju_api_upload_file": ("server.routers.files", "upload_file"),
    "manju_api_upload_style_image": ("server.routers.files", "upload_style_image"),
    "manju_api_upload_vertex_credential": ("server.routers.providers", "upload_vertex_credential"),
    "manju_api_upsert_quality_rating": ("server.routers.quality", "upsert_quality_rating"),
}

_MUTATING_ACTION_PREFIXES = (
    "activate_",
    "add_",
    "answer_",
    "apply_",
    "cancel_",
    "change_",
    "create_",
    "delete_",
    "finalize_",
    "full_update_",
    "generate_",
    "import_",
    "interrupt_",
    "patch_",
    "regenerate_",
    "reorder_",
    "replace_",
    "restore_",
    "run_",
    "save_",
    "send_",
    "update_",
    "upload_",
    "upsert_",
)


def _action(command: str) -> str:
    return command.removeprefix("manju_api_")


def is_mutating_ipc_command(command: str) -> bool:
    action = _action(command)
    if action.startswith(("discover_", "export_", "get_", "list_", "preview_", "test_")):
        return False
    return action.startswith(_MUTATING_ACTION_PREFIXES)


def project_name_from_ipc_payload(params: dict[str, Any]) -> str | None:
    path_params = params.get("pathParams")
    if not isinstance(path_params, dict):
        return None
    for key in ("project_name", "name"):
        value = path_params.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def should_start_worker_for_ipc_result(command: str, result: dict[str, Any]) -> bool:
    if result.get("success") is False:
        return False
    content = result.get("content") if isinstance(result, dict) else None
    value = content.get("value") if isinstance(content, dict) else None
    has_task_id = isinstance(value, dict) and ("task_id" in value or "task_ids" in value)
    action = _action(command)
    return has_task_id or action.startswith("generate_") or action in {"finalize_episode", "regenerate_grid"}


def _path_params_from_payload(params: dict[str, Any]) -> dict[str, Any]:
    path_params = params.get("pathParams") or {}
    if not isinstance(path_params, dict):
        raise ValueError("Invalid IPC pathParams")
    return {str(key): value for key, value in path_params.items()}


def _endpoint_for_command(command: str):
    target = _COMMAND_ENDPOINTS.get(command)
    if target is None:
        raise ValueError(f"Unsupported Manju IPC command: {command}")
    module_name, endpoint_name = target
    module = importlib.import_module(module_name)
    return getattr(module, endpoint_name)


async def dispatch_ipc_command(command: str, params: dict[str, Any]) -> dict[str, Any]:
    from utils.arcreel_desktop_routes import invoke_desktop_endpoint_result

    endpoint = _endpoint_for_command(command)
    return await invoke_desktop_endpoint_result(
        endpoint,
        params=params,
        path_params=_path_params_from_payload(params),
    )
