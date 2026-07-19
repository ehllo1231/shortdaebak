from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import __version__
from app.config import ConfigError, load_config
from app.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="DCInside 게시물에서 YouTube Shorts 후보 5개를 선별합니다.",
    )
    parser.add_argument("--config", required=True, type=Path, help="YAML 설정 파일 경로")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 이상이 필요합니다.")
    try:
        config = load_config(args.config)
        result = run_pipeline(config)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"환경 오류: {exc}", file=sys.stderr)
        return 2
    print(f"상태: {result.status}")
    print(f"결과: {result.output_directory.resolve()}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
