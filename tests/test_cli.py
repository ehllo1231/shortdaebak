from pathlib import Path
from types import SimpleNamespace

import app.__main__ as main_module
from app.__main__ import main


def test_cli_reports_missing_config(capsys) -> None:
    exit_code = main(["--config", "does-not-exist.yaml"])

    assert exit_code == 2
    assert "설정 오류" in capsys.readouterr().err


def test_cli_keeps_collect_as_default_command(monkeypatch, capsys) -> None:
    received = []
    monkeypatch.setattr(main_module, "load_config", lambda path: "config")
    monkeypatch.setattr(
        main_module,
        "run_pipeline",
        lambda config: (
            received.append(config)
            or SimpleNamespace(exit_code=0, status="success", output_directory=Path("output/run"))
        ),
    )

    exit_code = main(["--config", "config.yaml"])

    assert exit_code == 0
    assert received == ["config"]
    assert "상태: success" in capsys.readouterr().out


def test_cli_routes_script_command_with_run_and_ranks(monkeypatch) -> None:
    received = []
    monkeypatch.setattr(main_module, "load_config", lambda path: "config")
    monkeypatch.setattr(
        main_module,
        "run_script_pipeline",
        lambda config, run, ranks: (
            received.append((config, run, ranks))
            or SimpleNamespace(exit_code=0, status="success", output_directory=run / "scripts/1")
        ),
    )

    exit_code = main(
        [
            "script",
            "--config",
            "config.yaml",
            "--run",
            "output/2026-07-19/120000",
            "--ranks",
            "3,1",
        ]
    )

    assert exit_code == 0
    assert received == [
        (
            "config",
            Path("output/2026-07-19/120000"),
            (3, 1),
        )
    ]


def test_cli_routes_gui_command_without_loading_pipeline_config(monkeypatch) -> None:
    import app.gui

    received = []
    monkeypatch.setattr(
        app.gui,
        "launch_gui",
        lambda path: received.append(path) or 0,
    )

    exit_code = main(["gui", "--config", "config.yaml"])

    assert exit_code == 0
    assert received == [Path("config.yaml")]


def test_windows_gui_launcher_uses_project_venv_and_gui_command() -> None:
    launcher = Path("run_gui.bat").read_text(encoding="utf-8")

    assert '.venv\\Scripts\\python.exe" -m app gui --config config.yaml' in launcher
    assert 'cd /d "%~dp0"' in launcher
