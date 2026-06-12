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

    The grid source image is always a 2x2 board. Groups with fewer than four
    real storyboard shots keep the remaining cells as placeholders so refresh
    and preview rendering never collapse back into a one-column layout.

    Args:
        num_scenes: Number of scenes to display in the grid.
        aspect_ratio: Aspect ratio string (e.g. "16:9", "9:16", "4:3").

    Returns:
        GridLayout for 1-4 scenes, otherwise None.
    """
    if num_scenes < 1:
        return None
    if num_scenes > 4:
        return None

    rows, cols = 2, 2
    grid_aspect_ratio = _grid_aspect_ratio(aspect_ratio, rows, cols)

    return GridLayout(
        grid_size="grid_4",
        rows=rows,
        cols=cols,
        grid_aspect_ratio=grid_aspect_ratio,
        cell_count=rows * cols,
        placeholder_count=rows * cols - num_scenes,
    )


def plan_grid_chunk_sizes(num_scenes: int) -> list[int]:
    """Split a continuous scene group into 1-4 sized grid batches."""
    if num_scenes <= 0:
        return []
    chunks: list[int] = []
    remaining = num_scenes
    while remaining > 0:
        size = min(4, remaining)
        chunks.append(size)
        remaining -= size
    return chunks
