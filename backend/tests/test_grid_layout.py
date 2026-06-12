"""Tests for grid layout calculator."""

import pytest

from lib.grid.layout import calculate_grid_layout, plan_grid_chunk_sizes, resolve_storyboard_aspect_ratio
from lib.grid.models import GridGeneration, build_frame_chain


class TestCalculateGridLayout:
    def test_single_scene_uses_four_cell_grid(self):
        layout = calculate_grid_layout(1, "16:9")
        assert layout is not None
        assert layout.grid_size == "grid_4"
        assert layout.rows == 2
        assert layout.cols == 2
        assert layout.grid_aspect_ratio == "16:9"
        assert layout.cell_count == 4
        assert layout.placeholder_count == 3

    def test_2_scenes_horizontal_uses_four_cell_grid(self):
        layout = calculate_grid_layout(2, "16:9")
        assert layout is not None
        assert layout.grid_size == "grid_4"
        assert layout.rows == 2
        assert layout.cols == 2
        assert layout.grid_aspect_ratio == "16:9"
        assert layout.cell_count == 4
        assert layout.placeholder_count == 2

    def test_3_scenes_vertical_uses_four_cell_grid(self):
        layout = calculate_grid_layout(3, "9:16")
        assert layout is not None
        assert layout.grid_size == "grid_4"
        assert layout.rows == 2
        assert layout.cols == 2
        assert layout.grid_aspect_ratio == "9:16"
        assert layout.cell_count == 4
        assert layout.placeholder_count == 1

    def test_4_scenes_horizontal(self):
        layout = calculate_grid_layout(4, "16:9")
        assert layout is not None
        assert layout.grid_size == "grid_4"
        assert layout.rows == 2
        assert layout.cols == 2
        assert layout.grid_aspect_ratio == "16:9"
        assert layout.cell_count == 4
        assert layout.placeholder_count == 0

    def test_4_scenes_vertical(self):
        layout = calculate_grid_layout(4, "9:16")
        assert layout is not None
        assert layout.grid_size == "grid_4"
        assert layout.rows == 2
        assert layout.cols == 2
        assert layout.grid_aspect_ratio == "9:16"
        assert layout.cell_count == 4
        assert layout.placeholder_count == 0

    def test_above_4_returns_none(self):
        assert calculate_grid_layout(5, "16:9") is None

    def test_zero_returns_none(self):
        assert calculate_grid_layout(0, "16:9") is None


class TestGridLayoutPixelDimensions:
    def test_16_9_pixel_dimensions(self):
        layout = calculate_grid_layout(4, "16:9")
        assert layout is not None
        width, height = layout.pixel_dimensions()
        assert width > 0
        assert height > 0
        # 16:9 ratio
        assert abs(width / height - 16 / 9) < 0.01

    def test_9_16_pixel_dimensions(self):
        layout = calculate_grid_layout(4, "9:16")
        assert layout is not None
        width, height = layout.pixel_dimensions()
        assert width > 0
        assert height > 0
        # 9:16 ratio
        assert abs(width / height - 9 / 16) < 0.01


class TestBuildFrameChain:
    def test_rejects_more_scenes_than_cells(self):
        with pytest.raises(ValueError, match="scene_ids to fit cells"):
            build_frame_chain(["S1", "S2", "S3", "S4", "S5"], rows=2, cols=2)

    def test_4_scenes_grid_4(self):
        chain = build_frame_chain(["E1S01", "E1S02", "E1S03", "E1S04"], rows=2, cols=2)
        assert len(chain) == 4
        assert chain[0].frame_type == "first"
        assert chain[0].next_scene_id == "E1S01"
        assert chain[1].frame_type == "transition"
        assert chain[1].prev_scene_id == "E1S01"
        assert chain[1].next_scene_id == "E1S02"
        assert chain[3].frame_type == "transition"
        assert chain[3].prev_scene_id == "E1S03"
        assert chain[3].next_scene_id == "E1S04"

    def test_3_scenes_fills_remaining_cell_with_placeholder(self):
        chain = build_frame_chain(["S1", "S2", "S3"], rows=2, cols=2)
        assert len(chain) == 4
        assert [c.frame_type for c in chain] == ["first", "transition", "transition", "placeholder"]
        assert chain[3].next_scene_id is None

    def test_row_col_assignment(self):
        chain = build_frame_chain(["A", "B", "C", "D"], rows=2, cols=2)
        assert (chain[0].row, chain[0].col) == (0, 0)
        assert (chain[1].row, chain[1].col) == (0, 1)
        assert (chain[2].row, chain[2].col) == (1, 0)
        assert (chain[3].row, chain[3].col) == (1, 1)


class TestGridGeneration:
    def test_create(self):
        grid = GridGeneration.create(
            episode=1,
            script_file="ep1.json",
            scene_ids=["E1S01", "E1S02", "E1S03", "E1S04"],
            rows=2,
            cols=2,
            grid_size="grid_4",
            provider="test",
            model="test-m",
        )
        assert grid.status == "pending"
        assert grid.cell_count == 4
        assert len(grid.frame_chain) == 4
        assert grid.id.startswith("grid_")


class TestPlanGridChunkSizes:
    def test_single_scene_is_grid_batch(self):
        assert plan_grid_chunk_sizes(1) == [1]

    def test_terminal_splits_use_max_four(self):
        assert plan_grid_chunk_sizes(5) == [4, 1]
        assert plan_grid_chunk_sizes(6) == [4, 2]
        assert plan_grid_chunk_sizes(7) == [4, 3]
        assert plan_grid_chunk_sizes(8) == [4, 4]

    def test_larger_splits_keep_max_4(self):
        assert plan_grid_chunk_sizes(9) == [4, 4, 1]
        assert plan_grid_chunk_sizes(10) == [4, 4, 2]
        assert plan_grid_chunk_sizes(12) == [4, 4, 4]


class TestResolveStoryboardAspectRatio:
    def test_string_aspect_ratio(self):
        assert resolve_storyboard_aspect_ratio({"aspect_ratio": "16:9"}) == "16:9"

    def test_typed_storyboard_aspect_ratio(self):
        project = {"aspect_ratio": {"storyboards": "9:16", "videos": "16:9"}}
        assert resolve_storyboard_aspect_ratio(project) == "9:16"

    def test_fallback_uses_content_mode(self):
        assert resolve_storyboard_aspect_ratio({"content_mode": "drama"}) == "16:9"
