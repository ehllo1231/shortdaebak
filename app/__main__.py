from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import __version__
from app.config import ConfigError, load_config
from app.pipeline import run_pipeline
from app.scripting import ScriptInputError, run_script_pipeline


def _parse_ranks(value: str) -> tuple[int, ...]:
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise argparse.ArgumentTypeError("순위를 1,3처럼 쉼표로 구분해 입력하세요.")
    try:
        ranks = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("후보 순위는 정수여야 합니다.") from exc
    if any(rank <= 0 for rank in ranks):
        raise argparse.ArgumentTypeError("후보 순위는 1 이상이어야 합니다.")
    if len(set(ranks)) != len(ranks):
        raise argparse.ArgumentTypeError("중복된 후보 순위를 지정할 수 없습니다.")
    return ranks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="YouTube Shorts 후보를 선별하고 선택한 후보의 대본을 생성합니다.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("collect", "script", "gui"),
        default="collect",
        help="collect(기본값): 후보 선별, script: 대본 생성, gui: 데스크톱 GUI",
    )
    parser.add_argument("--config", required=True, type=Path, help="YAML 설정 파일 경로")
    parser.add_argument("--run", type=Path, help="script 명령에서 사용할 후보 실행 폴더")
    parser.add_argument(
        "--ranks",
        type=_parse_ranks,
        help="script 명령에서 대본으로 만들 후보 순위(예: 1,3)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 이상이 필요합니다.")
    if args.command == "script" and (args.run is None or args.ranks is None):
        parser.error("script 명령에는 --run과 --ranks가 필요합니다.")
    if args.command != "script" and (args.run is not None or args.ranks is not None):
        parser.error("--run과 --ranks는 script 명령에서만 사용할 수 있습니다.")
    if args.command == "gui":
        from app.gui import GuiUnavailableError, launch_gui

        try:
            return launch_gui(args.config)
        except ConfigError as exc:
            print(f"설정 오류: {exc}", file=sys.stderr)
            return 2
        except (OSError, GuiUnavailableError) as exc:
            print(f"GUI 오류: {exc}", file=sys.stderr)
            return 2
    try:
        config = load_config(args.config)
        if args.command == "script":
            result = run_script_pipeline(config, args.run, args.ranks)
        else:
            result = run_pipeline(config)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    except ScriptInputError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"환경 오류: {exc}", file=sys.stderr)
        return 2
    print(f"상태: {result.status}")
    print(f"결과: {result.output_directory.resolve()}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
