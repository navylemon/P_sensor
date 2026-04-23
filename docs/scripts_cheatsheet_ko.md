# scripts 폴더 치트시트

최종 갱신: 2026-04-23

이 문서는 저장소 루트의 `scripts/` 폴더에 있는 PowerShell 스크립트가 각각 무엇을 하는지 빠르게 확인하기 위한 요약이다.

## 기본 전제

- 모든 명령은 저장소 루트에서 실행하는 것을 기준으로 한다.
- 대부분의 실행 스크립트는 먼저 `.venv`를 찾는다. 없다면 `.\scripts\setup_env.ps1`를 먼저 실행한다.
- `run_stage_app.ps1`, `check_stage.ps1`, `run_automation_smoke.ps1`는 실제 스테이지나 DAQ 하드웨어를 움직이거나 접근할 수 있으므로, 설정 파일과 COM 포트가 맞는지 먼저 확인한다.

## 한눈에 보기

### 환경 준비

`setup_env.ps1`

- 용도: `.venv` 생성/복구, 의존성 설치, `requirements.txt` 동기화
- 실행: `.\scripts\setup_env.ps1`

### 앱 실행

`run_app.ps1`

- 용도: 기본 GUI 실행. 현재는 `io` 프로파일 실행
- 실행: `.\scripts\run_app.ps1`

`run_io_app.ps1`

- 용도: `io` 프로파일 GUI 실행
- 실행: `.\scripts\run_io_app.ps1`

`run_ai_app.ps1`

- 용도: `ai` 프로파일 GUI 실행
- 실행: `.\scripts\run_ai_app.ps1`

`run_automation_app.ps1`

- 용도: `automation` 프로파일 GUI 실행
- 실행: `.\scripts\run_automation_app.ps1`

`run_stage_app.ps1`

- 용도: SHOT-702/OSMS20-35 스테이지 전용 터치 친화 GUI 실행
- 실행: `.\scripts\run_stage_app.ps1`

### 자동화/장비 점검

`run_automation_smoke.ps1`

- 용도: 자동화 레시피 smoke 실행
- 실행: `.\scripts\run_automation_smoke.ps1 --no-motion`

`check_stage.ps1`

- 용도: SHOT-702/OSMS20-35 로컬 설정으로 스테이지 수동 점검
- 실행: `.\scripts\check_stage.ps1 --status`

### 패키지 관리

`pip_sync.ps1`

- 용도: `.venv`의 `pip` 실행 후 install/uninstall 시 requirements 자동 갱신
- 실행: `.\scripts\pip_sync.ps1 install PACKAGE_NAME`

`freeze_requirements.ps1`

- 용도: 현재 `.venv` 패키지 목록으로 `requirements.txt` 재생성
- 실행: `.\scripts\freeze_requirements.ps1`

### 빌드/아카이브

`build_exe.ps1`

- 용도: `P_sensor.spec`로 PyInstaller exe 빌드
- 실행: `.\scripts\build_exe.ps1`

`run_archive_v02.ps1`

- 용도: 보관된 v0.2 앱 실행
- 실행: `.\scripts\run_archive_v02.ps1`

## 환경/패키지 관리

### `setup_env.ps1`

개발 환경을 준비하는 첫 실행 스크립트다.

주요 동작:

- 저장소 루트의 `.venv`를 생성한다.
- Python 탐색 순서: `PROJECT_PYTHON` 환경 변수, `C:\python\python.exe`, `py -3`, `python`.
- pip이 깨졌거나 없으면 Python 내장 `ensurepip` wheel에서 pip을 복구한다.
- `.venv\Scripts\Activate.ps1`, `activate.bat`, `pip.bat` 계열 wrapper를 보정한다.
- `requirements.txt`에 패키지가 있으면 설치한다.
- 마지막에 `freeze_requirements.ps1`를 호출해 `requirements.txt`를 현재 환경 기준으로 다시 쓴다.

대표 명령:

```powershell
.\scripts\setup_env.ps1
```

기존 `.venv`를 백업 이름으로 밀어두고 새로 만들 때:

```powershell
.\scripts\setup_env.ps1 -Recreate
```

주의:

- `-Recreate`는 기존 `.venv`를 삭제하지 않고 `.venv_backup_yyyyMMdd_HHmmss` 형태로 이름을 바꾼다.
- `requirements.txt`가 자동 갱신되므로 실행 후 Git 변경 사항에 `requirements.txt`가 잡힐 수 있다.

### `pip_sync.ps1`

프로젝트 `.venv`의 pip을 실행하는 wrapper다.

주요 동작:

- `.\.venv\Scripts\python.exe -m pip ...` 형태로 pip 명령을 실행한다.
- 첫 인자가 `install` 또는 `uninstall`이면 성공 후 `freeze_requirements.ps1`를 자동 실행한다.

대표 명령:

```powershell
.\scripts\pip_sync.ps1 install pyserial
.\scripts\pip_sync.ps1 uninstall pyserial
.\scripts\pip_sync.ps1 list
```

주의:

- 패키지 추가/삭제는 이 스크립트를 쓰는 것이 `requirements.txt` 누락을 줄이는 기본 흐름이다.

### `freeze_requirements.ps1`

현재 `.venv`의 `pip freeze` 결과로 `requirements.txt`를 다시 만든다.

대표 명령:

```powershell
.\scripts\freeze_requirements.ps1
```

주의:

- `requirements.txt`를 직접 편집한 내용은 이 스크립트 실행 시 덮어써진다.

## 앱 실행

### `run_app.ps1`

현재 기본 실행 스크립트다. 내부적으로 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m p_sensor --profile io
```

대표 명령:

```powershell
.\scripts\run_app.ps1
```

참고:

- 현재 `run_app.ps1`와 `run_io_app.ps1`는 같은 동작을 한다.

### `run_io_app.ps1`

`io` 프로파일로 GUI를 실행한다. DAQ 입출력 중심의 기본 앱 프로파일이다.

대표 명령:

```powershell
.\scripts\run_io_app.ps1
```

### `run_ai_app.ps1`

`ai` 프로파일로 GUI를 실행한다. 입력 채널 중심 프로파일을 확인할 때 사용한다.

대표 명령:

```powershell
.\scripts\run_ai_app.ps1
```

### `run_automation_app.ps1`

`automation` 프로파일로 GUI를 실행한다. 자동화 패널/레시피 흐름을 포함한 앱을 확인할 때 사용한다.

대표 명령:

```powershell
.\scripts\run_automation_app.ps1
```

### `run_stage_app.ps1`

SHOT-702 + OSMS20-35 스테이지 전용 GUI를 실행한다. 앱은 기본적으로 Windows 제목 표시줄과 종료 버튼이 보이는 최대화 창으로 열리며, Stage 1 또는 Stage 1+2 조작 패널을 한 화면에 표시한다.

내부적으로 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m p_sensor --profile stage --config dev_local\config\stage_shot702_osms20_35.local.json
```

대표 명령:

```powershell
.\scripts\run_stage_app.ps1
```

동일한 직접 실행 명령:

```powershell
.\.venv\Scripts\python.exe -m p_sensor --profile stage
.\.venv\Scripts\python.exe -m p_sensor --profile stage --config dev_local\config\stage_shot702_osms20_35.local.json
p-sensor-stage
```

주요 기능:

- 확정 장비 `OPTOSIGMA SHOT-702` / `OPTOSIGMA OSMS20-35` 명시
- Stage 1 또는 Stage 1+2 조작 패널 선택
- 큰 버튼 기반 `+ 이동`, `- 이동`, `0 mm 이동`, `현재 0설정`, `원점복귀`, `감속 정지`, `비상 정지`
- `터치스크린 온리` 모드에서 숫자 입력칸 터치 시 가상 키패드 표시

주의:

- 연결 뒤 이동 버튼, 원점복귀, 현재 0설정, 모터 홀드/프리, 속도 적용은 실제 컨트롤러에 명령을 보낸다.
- 먼저 `상태 새로고침`과 위치 표시를 확인하고, 실제 이동은 작은 이동량부터 확인한다.
- PowerShell 실행 정책으로 `.ps1` 실행이 막히면 `powershell -ExecutionPolicy Bypass -File .\scripts\run_stage_app.ps1`로 실행할 수 있다.

## 자동화 smoke

### `run_automation_smoke.ps1`

자동화 레시피를 CLI에서 한 번 실행해보는 smoke 테스트용 스크립트다.

기본값:

- 앱/DAQ 설정: `config/channel_settings_automation.example.json`
- 레시피: `config/experiment_recipe_smoke.example.json`
- 모션 설정 후보: `dev_local/config/stage_shot702_osms20_35.local.json`

대표 명령:

```powershell
.\scripts\run_automation_smoke.ps1 --no-motion --session-label smoke_dry_run
.\scripts\run_automation_smoke.ps1 --session-label shot702_smoke_real
```

주요 옵션:

| 옵션 | 의미 |
| --- | --- |
| `-Config <path>` | 앱/DAQ 설정 파일 지정 |
| `-Recipe <path>` | 자동화 레시피 파일 지정 |
| `-MotionConfig <path>` | 스크립트 레벨의 기본 모션 설정 경로 변경 |
| `--no-motion` | 실제 모션 대신 NoOp 모션 브리지 사용 |
| `--allow-ni` | 설정이 NI backend를 요구할 때 실제 NI backend 허용 |
| `--include-ao` | 앱 설정의 AO 채널을 제거하지 않고 유지 |
| `--session-label <name>` | 저장 세션 라벨 지정 |
| `--home-on-connect` | 모션 설정의 home-on-connect 허용 |
| `--set-speed-on-connect` | 연결 시 SHOT 속도 설정 적용 |

주의:

- `--no-motion`이 없으면 실제 SHOT 모션 설정을 찾고, 가능한 경우 스테이지 제어를 시도한다.
- `--allow-ni`가 없으면 설정 파일이 `ni` backend를 요구해도 실제 NI DAQ 접근을 막는다.
- 실행 결과는 세션 ID, 세션 폴더, summary 경로, step별 측정 파일 경로로 출력된다.

## 스테이지 수동 점검

스테이지 점검 스크립트는 내부적으로 Python CLI인 `p_sensor.motion.shot_cli`를 실행한다.

### `check_stage.ps1`

SHOT-702 + OSMS20-35 기준 로컬 설정으로 스테이지를 점검한다.

기본 설정:

```text
dev_local/config/stage_shot702_osms20_35.local.json
```

대표 명령:

```powershell
.\scripts\check_stage.ps1 --status
.\scripts\check_stage.ps1 --axis 1 --jog
.\scripts\check_stage.ps1 --axis 1 --hold --origin --origin-zero
.\scripts\check_stage.ps1 --axis 1 --hold --goto-origin --status
.\scripts\check_stage.ps1 --axis 1 --set-speed --calibrate-nominal
```

확정 운용 기준:

- 별도 요청이 없으면 SHOT-702의 `axis 1`/driver 1만 움직인다.
- SHOT-702 기계 원점복귀는 `H:1` 형식으로 수행한다.
- `--goto-origin`은 logical origin, 즉 `0 mm` 절대 위치로 복귀한다.
- `--calibrate-nominal`은 origin 시도 후 방향키 jog로 조정하고, `n`을 누르면 현재 위치를 nominal/logical zero로 설정한다.
- jog 기본값은 좌/우 `0.1 mm`, 위/아래 `1.0 mm`다.

공통 주요 옵션:

| 옵션 | 의미 |
| --- | --- |
| `-Config <path>` | 기본 로컬 설정 대신 다른 SHOT JSON 설정 사용 |
| `--status` | 상태와 현재 위치 출력. 별도 동작이 없으면 기본 동작 |
| `--port COM10` | 시리얼 포트 지정 |
| `--axis 1` 또는 `--axis 2` | 제어 축 지정 |
| `--baudrate 9600` | RS-232C baudrate 지정 |
| `--pulses-per-mm <value>` | mm/pulse 변환 계수 지정 |
| `--min-position-mm <value>` | 소프트웨어 하한 지정 |
| `--max-position-mm <value>` | 소프트웨어 상한 지정 |
| `--no-limits` | 소프트웨어 이동 제한 비활성화 |
| `--set-speed` | 연결 시 속도 설정 적용 |
| `--minimum-speed-pps <value>` | `--set-speed`용 최소 속도 |
| `--maximum-speed-pps <value>` | `--set-speed`용 최대 속도 |
| `--acceleration-ms <value>` | `--set-speed`용 가감속 시간 |
| `--hold-on-connect` | 연결 시 모터 hold |
| `--hold` | 선택 축 모터 hold |
| `--free` | 선택 축 모터 free |
| `--home +` 또는 `--home -` | 지정 방향으로 home |
| `--origin` | 설정의 origin 방향 기준으로 원점 복귀 |
| `--origin-direction +` 또는 `--origin-direction -` | `--origin` 방향 override |
| `--origin-zero` | `--origin` 완료 후 논리 원점 재설정 |
| `--zero` | 현재 위치를 논리 원점으로 설정 |
| `--goto-origin` | 선택 축을 logical origin인 `0 mm` 절대 위치로 이동 |
| `--calibrate-nominal` | origin 시도 후 방향키 jog로 조정하고 `n`으로 nominal/logical zero 설정 |
| `--move-relative-mm <mm>` | 상대 이동 |
| `--move-absolute-mm <mm>` | 절대 위치로 이동 |
| `--wait` | 이동 명령 후 ready까지 대기 |
| `--jog` | 방향키 jog 모드 |
| `--jog-step-mm <mm>` | 좌/우 방향키 fine jog 거리. 기본값 `0.1` |
| `--jog-large-step-mm <mm>` | 위/아래 방향키 coarse jog 거리. 기본값 `1.0` |

주의:

- `--move-*`, `--home`, `--origin`, `--goto-origin`, `--calibrate-nominal`, `--jog`는 실제 스테이지를 움직인다.
- jog 모드는 Windows 콘솔에서 방향키를 읽는다. `q`는 종료, `s`는 상태 출력, Space는 emergency stop, 보정 모드의 `n`은 현재 위치 nominal/logical zero 설정이다.
- `--no-limits`는 안전 제한을 해제하므로 실제 장비에서는 신중히 사용한다.

## 빌드/아카이브

### `build_exe.ps1`

PyInstaller로 Windows 실행 파일을 만든다.

주요 동작:

- `.venv\Scripts\python.exe`를 사용한다.
- 저장소 루트의 `P_sensor.spec`를 사용한다.
- 기존 `dist\P_sensor.exe`가 있으면 먼저 삭제한다.
- PyInstaller workpath는 `dev_local\tmp\pyinstaller_yyyyMMdd_HHmmss` 아래에 만든다.

대표 명령:

```powershell
.\scripts\build_exe.ps1
```

주의:

- 실행 중인 `dist\P_sensor.exe`가 있으면 삭제에 실패하므로 앱을 닫고 다시 실행한다.
- `.venv`에 `PyInstaller`가 설치되어 있어야 한다. 개발 의존성이 빠졌다면 `.\scripts\pip_sync.ps1 install pyinstaller` 또는 `.\scripts\setup_env.ps1`로 환경을 맞춘다.

### `run_archive_v02.ps1`

보관된 v0.2 앱을 현재 `.venv` Python으로 실행한다.

주요 동작:

- `P_sensor_v0.2_archive_20260414\src`를 `PYTHONPATH`로 잡는다.
- 작업 디렉터리를 `P_sensor_v0.2_archive_20260414`로 바꾼 뒤 `python -m p_sensor`를 실행한다.

대표 명령:

```powershell
.\scripts\run_archive_v02.ps1
```

사용 목적:

- 현재 앱과 v0.2 동작을 비교하거나, 과거 버전에서 정상 동작하던 흐름을 확인할 때 사용한다.
