from app.__main__ import main


def test_cli_reports_missing_config(capsys) -> None:
    exit_code = main(["--config", "does-not-exist.yaml"])

    assert exit_code == 2
    assert "설정 오류" in capsys.readouterr().err
