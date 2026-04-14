# P_sensor

최종 갱신: 2026-04-06

`NI cDAQ-9174` + `NI 9234` 기반 저항 센서 측정 GUI 프로젝트다. 현재 저장소는 배포에 필요한 실행 코드와 공용 문서를 유지하고, 테스트 코드와 실험 산출물은 `dev_local/` 아래로 분리하는 구조를 사용한다.

## 현재 구현 상태

- `simulation` 백엔드와 `ni` 백엔드를 모두 지원한다.
- 기본 예제 설정은 8채널, 2모듈(`cDAQ1Mod1`, `cDAQ1Mod2`) 기준이다.
- 측정 중 채널별 저항값과 전압을 모듈 카드 형태로 표시한다.
- 그래프는 저항/전압을 개별적으로 켜고 끌 수 있고, `10 s`, `1 min`, `5 min`, `All` 범위를 지원한다.
- 측정 시작 시 CSV를 생성하고, 실행 중 샘플을 즉시 append 한다.
- 설정 JSON 불러오기/저장, 창 크기와 splitter 위치 복원, 로그 표시가 구현돼 있다.

## 현재 제한 사항

- 채널의 상세 파라미터(`bridge_type`, `excitation_voltage`, `nominal_resistance_ohm`, `zero_offset`, `calibration_scale`)는 현재 GUI에서 직접 편집하지 않고 JSON 설정 파일로 관리한다.
- UI의 채널 표는 모듈/포트 단위 활성화 토글 중심이다.
- NI 백엔드는 `NI 9234` 최소 샘플링 제약 때문에 내부적으로 최소 `1652 Hz` 이상으로 읽고, 목표 표시 주기에 맞춰 평균값을 사용한다.
- 자동 장비 목록 표시 UI는 아직 없고, 연결 성공/실패는 상태 메시지와 오류 대화상자로 확인한다.

## Quick Start

```powershell
.\scripts\setup_env.ps1
.\scripts\run_app.ps1
```

단일 실행 파일 빌드:

```powershell
.\scripts\build_exe.ps1
```

빌드 결과:

```text
dist\P_sensor.exe
```

테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

패키지 추가 또는 제거:

```powershell
.\scripts\pip_sync.ps1 install <package>
.\scripts\pip_sync.ps1 uninstall <package>
```

의존성 목록만 다시 동기화:

```powershell
.\scripts\freeze_requirements.ps1
```

## 실행과 설정

- 기본 설정 파일: `config/channel_settings.example.json`
- 기본 백엔드: `simulation`
- 실제 장비 사용 시: 설정 JSON의 `backend`를 `ni`로 변경
- 기본 CSV 저장 경로: `dev_local/exports`
- 기본 히스토리 길이: `300초`

## 프로젝트 구조

- `src/p_sensor/`: 애플리케이션 본체
- `src/p_sensor/acquisition/`: 시뮬레이션 및 NI 취득 백엔드
- `src/p_sensor/ui/`: 메인 윈도우와 모듈 카드 UI
- `config/`: 공용 설정 예제
- `scripts/`: 환경 구성, 실행, requirements 동기화 스크립트
- `docs/`: 프로젝트 명세, 저장소 정책, 협업 문서
- `dev_local/`: 테스트, 예제, CSV, 임시 파일, 개인 설정

## 로컬 전용 작업 영역

다음 경로는 Git 추적 대상이 아니다.

- `dev_local/tests/`
- `dev_local/examples/`
- `dev_local/exports/`
- `dev_local/tmp/`
- `dev_local/scratch/`
- `dev_local/config/`

세부 기준은 `docs/repository_policy_ko.md`를 따른다.

## 문서 안내

- 프로젝트 진행 현황과 구현 범위: `docs/project_spec_ko.md`
- 저장소 포함/제외 원칙: `docs/repository_policy_ko.md`
- GitHub + VS Code 협업 절차: `docs/github_vscode_cheatsheet_ko.md`
