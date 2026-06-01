import json
import zipfile

from server.services.asset_archive import AssetArchiveOptions, AssetArchiveService


def test_asset_archive_exports_selected_asset_dirs_and_style_favorites(tmp_path):
    projects_root = tmp_path / "projects"
    (projects_root / "_global_assets" / "character").mkdir(parents=True)
    (projects_root / "_global_assets" / "scene").mkdir(parents=True)
    (projects_root / "_style_favorites" / "images").mkdir(parents=True)
    (projects_root / "_global_assets" / "character" / "hero.png").write_bytes(b"png")
    (projects_root / "_global_assets" / "scene" / "palace.png").write_bytes(b"png")
    (projects_root / "_style_favorites" / "templates.json").write_text(
        json.dumps({"templates": [{"id": "favorite_demo"}]}),
        encoding="utf-8",
    )
    (projects_root / "_style_favorites" / "images" / "style.webp").write_bytes(b"webp")

    service = AssetArchiveService(projects_root)
    target, summary = service.export_to_path(
        tmp_path / "assets.zip",
        options=AssetArchiveOptions(
            asset_types=("character", "prop"),
            include_style_favorites=True,
            include_global_config=False,
        ),
        payload={
            "assets": [{"id": "a1", "type": "character", "name": "Hero"}],
            "global_config": None,
        },
    )

    assert target.exists()
    assert summary["assets"] == 1
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "arcreel-assets-export.json" in names
        assert "asset-library/assets.json" in names
        assert "projects-root.txt" in names
        assert "_global_assets/character/hero.png" in names
        assert "_global_assets/scene/palace.png" not in names
        assert "_style_favorites/templates.json" in names
        assert "_style_favorites/images/style.webp" in names
        assets_payload = json.loads(archive.read("asset-library/assets.json").decode("utf-8"))
        assert assets_payload["assets"][0]["name"] == "Hero"


def test_asset_archive_optionally_exports_global_config_files(tmp_path):
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True)
    (projects_root / ".system_config.json").write_text('{"legacy": true}', encoding="utf-8")
    (tmp_path / "vertex_keys").mkdir()
    (tmp_path / "vertex_keys" / "vertex_credentials.json").write_text("{}", encoding="utf-8")

    service = AssetArchiveService(projects_root)
    target, summary = service.export_to_path(
        tmp_path / "assets.zip",
        options=AssetArchiveOptions(
            asset_types=(),
            include_style_favorites=False,
            include_global_config=True,
        ),
        payload={
            "assets": [],
            "global_config": {"system_settings": [{"key": "default_video_backend"}]},
        },
    )

    assert target.exists()
    assert summary["global_config"] is True
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "global_config/config.json" in names
        assert "global_config/legacy/.system_config.json" in names
        assert "global_config/vertex_keys/vertex_credentials.json" in names
        config = json.loads(archive.read("global_config/config.json").decode("utf-8"))
        assert config["system_settings"][0]["key"] == "default_video_backend"
