# DCInside Shorts 후보·대본 제작기

공개 DCInside 정식·마이너 갤러리의 최근 게시물을 수집하고, 규칙 기반 필터와 로컬 Codex CLI로 YouTube Shorts 소재를 선정한 뒤, 사람이 선택한 후보를 45~60초 제작용 대본으로 변환하는 Windows 11용 CLI다.

이 프로그램은 이미지, 음성, 영상을 만들지 않는다. 후보와 대본은 사실 확인 결과가 아니며 제작 전에 사람이 원문과 위험 요소를 다시 검토해야 한다.

현재 구현과 향후 대본·이미지·영상 제작 모듈의 설계 방향은
[아키텍처 문서](docs/architecture.md)에 정리되어 있다.

## 필요 환경

- Windows 11
- Python 3.12 이상
- Node.js와 Codex CLI
- API 키가 아닌 ChatGPT 계정으로 로그인된 Codex CLI

Codex CLI는 PowerShell에서 다음과 같이 설치하고 로그인한다.

```powershell
npm install -g @openai/codex
codex login
codex login status
```

`codex login status`가 `Logged in using ChatGPT`를 표시해야 한다. API 키 방식으로 로그인돼 있으면 이 프로그램은 Codex 평가를 거부한다. 인증 방식을 바꾸려면 다음을 실행한다.

```powershell
codex logout
codex login
```

## 설치

PowerShell에서 프로젝트 폴더로 이동한 뒤 가상환경을 만든다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item config.example.yaml config.yaml
```

PowerShell이 가상환경 활성화를 막으면 현재 터미널에서만 다음을 실행한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

## 설정

`config.yaml`에서 반드시 `dcinside.galleries`를 실제 갤러리로 바꾼다.

```yaml
dcinside:
  galleries:
    - id: gallery_id_from_url
      name: 보고서에 표시할 이름
      type: major
```

- `id`: 갤러리 URL의 `id=` 값
- `name`: 보고서와 로그에 표시할 이름
- `type`: 정식 갤러리는 `major`, 마이너 갤러리는 `minor`

`example_gallery`는 실제 갤러리 ID가 아니다. 수집 전에 반드시 수정해야 한다. 잘못된 갤러리 유형을 지정하면 HTML 구조 변경 오류로 보일 수 있다.

주요 설정:

- `pages_per_gallery`: 갤러리당 읽을 최근 목록 페이지 수, 최대 20
- `request_interval_seconds`: DCInside 요청 사이 최소 간격
- `min_body_length`: 짧은 본문 제외 기준
- `excluded_keywords`: 제목이나 본문에 포함되면 제외할 문구
- `dedupe_history_days`: 성공한 이전 실행의 URL·게시물 ID를 중복으로 볼 기간, 0이면 이력 중복 제거 안 함
- `prefilter.candidate_count`: Codex에 전달할 규칙 기반 후보 수, 최대 100
- `prefilter.weights`: 최신성, 추천, 댓글, 조회, 본문 길이, 참여율 가중치
- `codex.final_candidate_count`: Codex가 최종 선정할 후보 수, 1 이상이고 `prefilter.candidate_count` 이하

가중치는 모두 0 이상이어야 하고 합계가 0이면 안 된다. 설정 키의 오타는 무시하지 않고 시작 단계에서 오류로 보고한다.

## GUI 실행

Windows 탐색기에서 `run_gui.bat`을 더블클릭하거나 PowerShell에서 다음 명령을 실행한다.

```powershell
python -m app gui --config config.yaml
```

GUI는 다음 두 탭으로 구성된다.

- `후보 생성`: 갤러리와 후보 수 등 기본 설정을 수정하고, 고급 영역에서 요청 간격·필터 가중치·Codex 설정 등을 조정한 뒤 후보 선정을 실행한다.
- `대본 생성`: output 폴더의 최근 성공 보고서를 고르거나 다른 `report.html`을 선택하고, 표시된 후보 중 원하는 항목만 체크해 대본을 생성한다.

갤러리를 추가할 때 정식·마이너 갤러리 URL을 붙여 넣으면 ID와 유형을 자동으로 인식한다. ID만 입력할 때는 유형을 직접 선택한다. 미니 갤러리는 지원하지 않는다.

`설정 저장`과 각 실행 버튼은 화면 값을 기존 설정 규칙으로 검증한 뒤 선택한 YAML 파일에 UTF-8로 저장한다. 저장 시 YAML은 표준 형식으로 다시 작성되므로 사용자 주석은 보존되지 않는다. `sandbox=read-only`와 `ephemeral=true`는 GUI에서 변경할 수 없는 안전 설정이다.

수집과 Codex 호출은 백그라운드에서 실행되며 창 아래에 진행률과 로그가 표시된다. 한 번에 하나의 작업만 실행할 수 있고, 실행 중에는 창을 닫을 수 없다. 완료 후 `결과 보고서 열기` 버튼으로 HTML을 기본 브라우저에서 확인한다.

## CLI 실행

```powershell
python -m app --config config.yaml
```

성공하면 결과 폴더를 출력한다. 보고서는 해당 폴더의 `report.html`을 브라우저로 열어 확인한다.

목록 수집 후 게시물 본문을 순차 요청하는 동안 다음과 같은 진행 상황이 약 2% 간격으로 갱신된다. 명령창에서는 같은 줄을 덮어쓰고, `run.log`에는 갱신 시점별 기록을 남긴다.

```text
실시간 베스트 갤러리 본문 수집 [######------------------] 65/249 (26.1%) | 성공 64, 실패 1 | 경과 01:42, 남은 약 04:49
```

```text
output/2026-07-19/123456/
├── raw_posts.json
├── prefiltered.json
├── candidates.json
├── report.html
├── run.json
├── run.log
└── codex_stderr.log
```

동일한 초에 재실행하면 `123456-01` 같은 새 폴더를 만들어 이전 결과를 덮어쓰지 않는다. `candidates.json`은 Codex 평가가 성공한 경우에만 생성된다.

### 선택 후보의 대본 생성

후보 보고서에서 제작할 순위를 고른 뒤, 성공한 후보 실행 폴더와 순위를 지정한다.

```powershell
python -m app script `
  --config config.yaml `
  --run output/2026-07-19/123456 `
  --ranks 1,3
```

`--ranks`는 쉼표로 구분하며 중복할 수 없다. Codex 후보 선정에 성공해 `candidates.json`이 있는 실행만 사용할 수 있다. 대본 결과는 원본 실행을 덮어쓰지 않고 다음 위치에 저장된다.

```text
output/2026-07-19/123456/scripts/150000/
├── topic_briefs.json
├── script_packages.json
├── script_report.html
├── script_run.json
├── script_run.log
└── codex_stderr.log
```

- `topic_briefs.json`: 커뮤니티 후보를 출처 독립적인 공통 입력으로 변환한 결과
- `script_packages.json`: 훅, 전개, 결말, 화면 자막, 시간과 검수 경고가 포함된 구조화 대본
- `script_report.html`: 구간별 타임라인과 녹음용 합본을 확인하는 보고서

동일한 초에 같은 후보 실행에서 대본 생성을 반복하면 `150000-01` 같은 새 폴더를 만든다. 대본 생성이 실패하면 입력과 진단 로그는 보존하지만 `script_packages.json`은 만들지 않는다.

종료 코드:

- `0`: Codex 평가까지 성공
- `2`: 설정 또는 출력 환경 오류
- `3`: 규칙 후보가 설정한 최종 후보 수보다 적음
- `4`: Codex 후보 평가 실패·비활성화 또는 대본 생성 실패
- `5`: 수집 차단 또는 수집 실패
- `6`: 예상하지 못한 내부 오류

## 선별 방식

규칙 필터는 선형 가중 합으로 0~100 점수를 만든다.

- 최신성은 72시간 반감기로 감쇠한다.
- 조회·추천·댓글은 값의 쏠림을 줄이기 위해 `log1p`를 적용한 뒤 현재 배치에서 정규화한다.
- 본문 길이는 1,000자에서 최댓값에 도달한다.
- 참여율은 `(추천 + 댓글) / 조회`를 사용한다.
- 유사 제목·본문의 비율이 90% 이상이면 근사 중복으로 보고 반응 수치가 높은 글을 남긴다.

Codex에는 규칙 기반 후보만 UTF-8 표준 입력으로 전달한다. 게시물 내용을 명령으로 취급하지 않도록 비신뢰 데이터 구간으로 표시하며, Codex는 임시 빈 폴더에서 읽기 전용·승인 없음·일회성 모드로 실행된다.
개별 본문은 평가 입력에서 6,000자로 제한하고 원본 길이와 자름 여부를 함께 표시한다. `raw_posts.json`에는 수집된 전체 본문이 남는다.

## 대본 작성 방식

대본 작성기는 DCInside 게시물이나 후보 파일을 직접 알지 못하고 `TopicBrief`라는 공통 계약만 입력받는다. 현재는 커뮤니티 후보 어댑터가 `candidates.json`과 `raw_posts.json`을 결합해 이 계약을 만든다. 향후 직접 작성한 주제도 같은 계약으로 변환하면 대본 작성기를 수정하지 않고 연결할 수 있다.

각 대본은 다음 다섯 구간을 정확히 하나씩 포함하며 전체 예상 시간은 45~60초다.

```text
hook → setup → development → payoff → closing
```

각 구간에는 내레이션, 화면 자막, 예상 초수, 원문 근거와 출처 ID가 포함된다. 마지막 구간은 시청자 질문으로 끝난다. 원문의 위험도와 검토 메모를 대본 결과에 그대로 유지하며, 위험도가 높아도 생성하되 HTML에 고위험 경고를 표시한다.

대본 생성도 게시물 내용을 신뢰할 수 없는 데이터로 취급한다. 입력 안의 명령을 따르지 않고, 임시 빈 폴더에서 읽기 전용·승인 없음·일회성 Codex 모드로 실행한다. 외부 사실 확인이나 웹 검색은 하지 않으며 모든 결과에 사람 검수 필수 표시를 남긴다.

## 테스트

단위 테스트는 저장된 HTML fixture와 가짜 Codex subprocess를 사용하므로 실제 DCInside나 Codex를 호출하지 않는다.

```powershell
ruff format --check .
ruff check .
pytest
python -m app --help
```

fixture 기반 전체 흐름만 다시 확인하려면 다음을 실행한다.

```powershell
pytest tests/test_pipeline.py
```

실제 Codex 호출은 사용량을 소모하므로 통합 마커를 명시한 경우에만 수행한다. 다음 명령은 후보 평가와 대본 생성의 실제 Codex 통합 테스트를 수행한다.

```powershell
pytest -m integration
```

## 제한사항

- DCInside의 HTML 구조가 변경되면 선택자와 fixture를 업데이트해야 한다.
- 공개 정식·마이너 갤러리만 지원하며 미니 갤러리는 지원하지 않는다.
- 로그인, CAPTCHA, 요청 제한, 봇 차단을 우회하지 않는다.
- 이미지만 있는 글은 본문이 빈 글로 제외될 수 있다.
- 댓글 본문은 추가 요청하지 않고 목록의 댓글 수만 사용한다.
- 대본은 커뮤니티 원문의 사실 여부를 검증하지 않으며 원문이 잘린 경우 일부 맥락이 누락될 수 있다.
- 직접 작성한 주제 입력은 아직 지원하지 않는다.
- Codex CLI 출력은 현재 버전의 문구를 통해 ChatGPT 인증을 확인한다. CLI 문구가 변경되면 인증 확인 코드를 업데이트해야 할 수 있다.
- Codex 평가는 언어 모델의 판단이며 사실 확인이나 법률 검토를 대체하지 않는다.
- 수집된 원문에 개인정보가 포함될 수 있으므로 `output` 폴더를 공개 저장소에 올리지 말아야 한다.

## 다음 MVP 후보

- 대상 갤러리별 수집 성공률과 HTML 구조 변경 감지
- 사람이 확정한 후보의 승인·반려 이력
- 원문 보관 기간과 자동 삭제 정책
- 직접 작성한 주제를 `TopicBrief`로 불러오는 입력 어댑터
- 대본 승인·수정 이력과 `Storyboard` 생성 단계
