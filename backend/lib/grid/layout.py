"""Grid layout calculator for grid-image-to-video feature."""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

# Base resolution for grid rendering (width reference for 16:9)
_BASE_WIDTH = 1920


@dataclass(frozen=True)
class GridLayout:
    """Describes the layout of a grid composed of multiple scene images."""

    grid_size: str
    rows: int
    cols: int
    grid_aspect_ratio: str
    cell_count: int
    placeholder_count: int

    def pixel_dimensions(self) -> tuple[int, int]:
        """Return (width, height) in pixels based on grid_aspect_ratio."""
        w_str, h_str = self.grid_aspect_ratio.split(":")
        w_ratio = int(w_str)
        h_ratio = int(h_str)
        # Scale so that the larger dimension matches the base reference
        if w_ratio >= h_ratio:
            width = _BASE_WIDTH
            height = round(_BASE_WIDTH * h_ratio / w_ratio)
        else:
            height = _BASE_WIDTH
            width = round(_BASE_WIDTH * w_ratio / h_ratio)
        return width, height


def _reduce_ratio(width: int, height: int) -> str:
    g = gcd(width, height)
    return f"{width // g}:{height // g}"


def _grid_aspect_ratio(cell_aspect_ratio: str, rows: int, cols: int) -> str:
    """Compute the full grid ratio while preserving each cell ratio."""
    w_str, h_str = cell_aspect_ratio.split(":")
    cell_w = int(w_str)
    cell_h = int(h_str)
    return _reduce_ratio(cell_w * cols, cell_h * rows)


def resolve_storyboard_aspect_ratio(project: dict) -> str:
    """Resolve the storyboard cell aspect ratio from legacy or typed project config."""
    raw = project.get("aspect_ratio")
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, dict):
        for key in ("storyboards", "storyboard", "videos", "video"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return "9:16" if project.get("content_mode", "narration") == "narration" else "16:9"


def calculate_grid_layout(num_scenes: int, aspect_ratio: str) -> GridLayout | None:
    """Calculate the appropriate grid layout for the given number of scenes.

    The grid source image always contains exactly 2-4 real storyboard shots.
    For 2/3 horizontal shots we stack panels vertically, and for 2/3 vertical
    shots we place panels in one row. This avoids overly wide/tall source
    images while preserving each cell ratio.

    Args:
        num_scenes: Number of scenes to display in the grid.
        aspect_ratio: Aspect ratio string (e.g. "16:9", "9:16", "4:3").

    Returns:
        GridLayout for 2-4 scenes, otherwise None for single-scene/non-grid batches.
    """
    if num_scenes <= 1:
        return None
    if num_scenes > 4:
        return None

    # Determine orientation by comparing width and height numerically.
    parts = aspect_ratio.split(":")
    w_ratio, h_ratio = int(parts[0]), int(parts[1])
    orientation = "horizontal" if w_ratio > h_ratio else "vertical"

    if num_scenes == 4:
        rows, cols = 2, 2
    elif orientation == "horizontal":
        rows, cols = num_scenes, 1
    else:
        rows, cols = 1, num_scenes

    grid_aspect_ratio = _grid_aspect_ratio(aspect_ratio, rows, cols)

    return GridLayout(
        grid_size=f"grid_{num_scenes}",
        rows=rows,
        cols=cols,
        grid_aspect_ratio=grid_aspect_ratio,
        cell_count=num_scenes,
        placeholder_count=0,
    )


def plan_grid_chunk_sizes(num_scenes: int) -> list[int]:
    """Split a continuous scene group into 2-4 sized grid batches.

    A single scene is intentionally omitted because it should use the normal
    storyboard flow, not grid generation.
    """
    if num_scenes <= 1:
        return []

    terminal: dict[int, list[int]] = {
        2: [2],
        3: [3],
        4: [4],
        5: [3, 2],
        6: [3, 3],
        7: [4, 3],
        8: [4, 4],
    }
    if num_scenes in terminal:
        return terminal[num_scenes]

    chunks: list[int] = []
    remaining = num_scenes
    while remaining > 8:
        chunks.append(4)
        remaining -= 4
    chunks.extend(terminal[remaining])
    return chunks
