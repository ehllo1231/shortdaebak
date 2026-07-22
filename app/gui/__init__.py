from __future__ import annotations

from pathlib import Path


class GuiUnavailableError(RuntimeError):
    pass


def launch_gui(config_path: Path) -> int:
    try:
        from app.gui.window import launch_gui as launch
    except ImportError as exc:
        raise GuiUnavailableError(f"Tkinter GUI 모듈을 불러올 수 없습니다: {exc}") from exc

    return launch(config_path)


__all__ = ["GuiUnavailableError", "launch_gui"]
