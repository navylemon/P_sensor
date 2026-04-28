# 저장소 구성 원칙

이 프로젝트는 배포에 필요한 실행 코드와 공용 문서만 저장소 루트에 두고, 테스트와 실험 중 생성되는 자산은 `dev_local/` 아래로 격리한다.

현재 개발 방향은 하나의 코어 코드베이스를 유지하면서 실행 프로필과 장비 어댑터만 분리하는 방식이다.

- AI 전용 측정 프로그램
- AI + AO 입출력 프로그램
- 리니어 스테이지 연동 자동화 프로그램
- 리니어 스테이지 수동 조작 단독 프로그램

즉, 프로그램 수가 늘어나더라도 `src/` 내부 로직과 GUI는 가능한 한 공용으로 유지하고, 차이는 진입점, 설정 프로필, 장비 어댑터에서 관리한다.

## 1. Git에 포함하는 영역

- `src/`
- `scripts/`
- `config/`
- `docs/`
- `README.md`
- `requirements.txt`
- `pyproject.toml`
- `.vscode/`
- `P_sensor.spec`
- `p_sensor.code-workspace`
- 추적이 필요한 아카이브 디렉터리
- 기타 공용 설정 파일

## 2. Git에 포함하지 않는 영역

다음 항목은 로컬 전용 자산으로 취급하며 Git 추적에서 제외한다.

- 테스트 코드와 테스트 중 생성되는 캐시
- 실험용 예제와 프로토타입
- 측정 CSV와 임시 분석 결과
- 개인 메모
- 장비별 개인 설정
- 설치와 부트스트랩 임시 파일
- 빌드 결과물
- 캐시 디렉터리
- 정리 대기 중인 임시 보관물

## 3. 로컬 전용 작업 영역

로컬 전용 자산은 모두 `dev_local/` 아래에 둔다.

- `dev_local/tests/`
- `dev_local/examples/`
- `dev_local/exports/`
- `dev_local/tmp/`
- `dev_local/scratch/`
- `dev_local/config/`
- `dev_local/hardware_checks/`
- `dev_local/cleanup_candidates/`

`dev_local/` 전체와 `pytest-cache-files-*` 같은 테스트 잔여물은 `.gitignore`에서 제외한다.

## 4. 프로그램 분기 운영 원칙

- 실행 모드는 별도 코드베이스로 복제하지 않는다.
- 공용 기능은 `src/p_sensor/` 아래에서 유지한다.
- 실행 차이는 프로필 기반 진입점에서만 둔다.
- GUI는 가능한 한 동일한 구조를 유지하고, 프로필에 따라 필요한 패널만 숨기거나 비활성화한다.
- 공용 설정 형식은 유지하되 프로그램별 기본 설정 파일은 분리할 수 있다.

향후 자동화 모드가 추가되더라도 동일한 원칙을 적용한다.

- 수동 모니터링, AO 제어, 자동 실험 실행은 하나의 코어 코드베이스 위에서 프로필로 분기한다.
- `MainWindow`는 조합 지점으로 두고, 측정 패널, 출력 패널, 자동화 패널은 점진적으로 분리 가능한 구조를 목표로 한다.
- 단일 DAQ 측정 루프는 다른 프로젝트에서도 재사용할 수 있도록 자동화 로직과 분리된 독립 모듈로 유지한다.

## 5. 장비 확장 원칙

- 장비별 SDK 의존 코드는 UI나 실험 시나리오 로직에 직접 넣지 않는다.
- NI DAQ, 리니어 스테이지, 향후 추가될 힘 센서나 보조 장비는 각각 추상 인터페이스 뒤에 둔다.
- 자동 실험 시퀀스는 "장비 제어 세부 구현"이 아니라 "실험 단계 정의"를 기준으로 작성한다.
- 재사용 가능한 단일 DAQ 측정 루프는 자동화 기능보다 하위 계층에 둔다.
- 특정 스테이지 제조사에 종속되는 초기화, 홈, 이동, 정지, 상태 조회 로직은 별도 어댑터 모듈에 한정한다.
- 장비 미확정 단계에서는 시뮬레이션 어댑터를 먼저 구현할 수 있는 구조를 우선한다.

현재 자동화 개발 기준 하드웨어는 다음과 같다.

- 리니어 스테이지: `OPTOSIGMA OSMS20-35`
- 스테이지 컨트롤러: `OPTOSIGMA SHOT-702`
- 검증된 연결 포트: 로컬 기준 `COM10`
- 확인된 컨트롤러 ROM: `V1.04`

위 조합을 기준으로 할 때 다음 원칙을 적용한다.

- 호스트 제어는 `SHOT-702`의 `RS-232C` 인터페이스를 기준으로 구현한다.
- 호스트 제어 명령은 SHOT 계열의 호스트 제어 명령을 기준으로 사용한다.
- `OSMS20-35`는 limit sensor normal close, origin sensor normal open 전제를 기준으로 한다.
- 변위-펄스 환산은 스테이지 해상도와 컨트롤러 step 설정에 따라 달라질 수 있으므로 코드에서 설정 가능하게 둔다.
- SHOT 계열 제어 구현은 `src/p_sensor/motion/shot_series.py`에 한정하고, 수동 점검 CLI는 `src/p_sensor/motion/shot_cli.py`, `scripts/check_stage.ps1`로 관리한다.
- `SHOT-102` 호환 전제는 사용하지 않는다. 문서, 테스트, UI 표기는 모두 `SHOT-702` 기준으로 유지한다.
- Stage 전용 GUI는 `SHOT-702`의 `driver 1`/`axis 1`과 `driver 2`/`axis 2`를 모두 선택 운용 대상으로 둔다. UI 선택지는 `Stage 1만`, `Stage 2만`, `Stage 1 + Stage 2`이며, 이동/원점/홀드/프리/속도 명령은 화면에 표시된 선택 대상에만 보낸다.
- Stage 1은 Z축 스테이지로 정의한다. 양의 방향은 Z축 위, 음의 방향은 Z축 아래 이동이다.
- Stage 2는 X축 스테이지로 정의한다. 양의 방향은 X축 우측, 음의 방향은 X축 좌측 이동이다.
- GUI의 이동 방향 안내는 정적 이미지 파일로 하드코딩하지 않고 코드로 그린다. Stage 선택 조합이 바뀌면 같은 규칙으로 도면과 라벨을 즉시 갱신한다.
- SHOT-702 기계 원점복귀 명령은 `H:<axis>` 형식이다. 예: 1축 원점복귀는 `H:1`.
- 논리 원점 설정은 현재 위치에서 `R:<axis>`로 수행한다. 명목 위치 보정 워크플로에서는 수동 jog 후 현재 위치를 nominal/logical zero로 설정한다.
- 최초 컨택점 자동인식은 Stage 1(Z축) 전용 보정 워크플로로 취급한다. 사용자가 먼저 Stage 1을 센서에서 충분히 위로 이격한 뒤 시작하고, 프로그램은 안전 속도와 소프트 리밋 안에서 Stage 1을 천천히 하강시키며 DAQ 저항 변화가 기준값을 넘는 최초 지점을 찾는다.
- 최초 컨택점 자동인식으로 찾은 위치는 기계 원점이 아니라 `측정 시작 nominal contact point`로 기록한다. 필요하면 해당 위치를 자동화 레시피의 변위 `0 mm` 기준 또는 별도 접촉 기준 위치로 사용할 수 있지만, SHOT-702의 기계 원점과 혼동하지 않는다.
- 컨택점 자동인식은 저항 변화 임계값, 안정 확인 시간, 최대 탐색 거리, 하강 속도, 중단 조건을 명시적으로 설정할 수 있어야 하며, 비상 정지와 사용자 중단은 항상 즉시 우선한다.
- 2026-04-23 기준 최초 컨택점 자동인식의 독립 모듈은 `src/p_sensor/automation/contact.py`에 둔다. 이 모듈은 UI와 자동화 러너에 아직 직접 통합하지 않고, 추후 통합 과정에서 command bridge와 측정 서비스에 연결할 수 있는 준비 모듈로 유지한다.
- 논리 원점으로 복귀할 때는 절대 위치 `0 mm` 이동을 사용한다. 내부 명령은 `A:<axis>+P0` 다음 `G:`다.
- 수동 jog 기본값은 좌/우 방향키 `0.1 mm`, 위/아래 방향키 `1.0 mm`다. 보정 모드에서 `n`은 현재 위치를 nominal/logical zero로 설정한다.
- 2026-04-23 기준 수동 검증 완료 범위는 `status`, `+/-0.1 mm` 왕복, `+10 mm` 이동, 방향키 `jog`, SHOT-702 형식 `origin` 복귀, `origin-zero`, `goto-origin`이다.
- 2026-04-23 기준 실장비 연결 확인은 `COM10`, ROM `V1.04`, `axis 1`/`axis 2` status 응답 기준으로 기록한다.
- 2026-04-20 기준 자동화 smoke 검증 완료 범위는 시뮬레이션 DAQ와 실제 `ShotCommandBridge`를 조합한 `0.5 mm -> 측정 창 -> 0.0 mm` 단일 step 실행이다.
- 자동화 오케스트레이션은 CLI를 직접 호출하지 않고 `ShotCommandBridge` 또는 동등한 명령 브리지 인터페이스를 통해서만 모션 계층을 사용한다.
- 실장비 이동 테스트는 자동 테스트에 포함하지 않는다. 단위 테스트는 명령 문자열, 설정 검증, 소프트 리밋, 브리지 변환만 검증하고 실제 이동은 수동 점검 절차로 분리한다.
- 공용 샘플 설정은 `config/stage_shot702_osms20_35.example.json`에 두되, 홈 방향, `pulses_per_mm`, 소프트 리밋은 `dev_local/config/`의 로컬 설정에서 관리한다. USB-serial 연결 순서에 따라 `COM` 번호가 바뀔 수 있으므로 메인 UI는 stage config load 버튼 없이도 현재 감지된 serial port 목록에서 SHOT-702 포트를 선택할 수 있어야 한다. 이 runtime port 선택은 장치 종류 추가가 아니라 로컬 연결 상태 선택으로 본다.

## 6. 아카이브 및 정리 기준

- 과거 버전 보관이 필요하면 날짜가 포함된 아카이브 디렉터리로 분리한다.
- 현재 비교 또는 검증에 직접 사용하는 아카이브는 루트에 둘 수 있다.
- 더 이상 직접 사용하지 않는 빌드 산출물, 메모, 캐시, 임시 복사본은 `dev_local/cleanup_candidates/`로 옮긴다.
- 루트의 `dist/` 같은 빌드 결과물은 장기 보관 대상이 아니면 루트에 두지 않는다.

## 7. 권장 운영 방식

- 실행 기능은 `src/`와 `scripts/`에서만 관리한다.
- 공용 설정 샘플은 `config/`에 둔다.
- 실제 측정 결과 기본 저장 경로는 `dev_local/exports/`로 유지한다.
- 테스트 파일은 `dev_local/tests/`에 두고 `pyproject.toml`의 `pytest` 설정과 일치시킨다.
- 장비별 또는 사용자별 설정은 `dev_local/config/`에 둔다.
- `config/stage_shot702_osms20_35.example.json` 같은 공용 샘플은 Git에 포함하고, 실제 `COM` 포트와 교정값은 `dev_local/config/`에 둔다.
- 하드웨어 점검 로그와 수동 검증 산출물은 `dev_local/hardware_checks/`에 둔다.
- 프로그램별 실행 스크립트는 `scripts/`에서 관리한다.
- 자동화 시나리오 샘플과 실험 레시피 예제는 `config/`에 둘 수 있고, 장비별 실제 값은 `dev_local/config/`에 둔다.

## 8. 작업 규칙

- 루트에 새 폴더를 추가할 때는 배포 필수 영역인지 먼저 판단한다.
- 배포와 무관한 산출물은 루트에 두지 않는다.
- 테스트 실행 후 생기는 캐시와 임시 폴더는 `dev_local/` 또는 ignore 패턴으로 정리한다.
- 공용 저장소에 올릴 필요가 없는 파일은 즉시 로컬 전용 영역으로 이동한다.
- 새로운 실행 모드를 추가할 때는 기존 코드를 복제하지 말고 프로필 또는 설정 분기로 먼저 해결 가능한지 검토한다.
- 아카이브 디렉터리를 수정할 때는 현재 본선 코드와의 역할 차이를 문서로 남긴다.
- 다른 프로젝트에서도 사용할 DAQ 측정 루프를 수정할 때는 자동화 기능 의존성이 역류하지 않도록 경계를 확인한다.

## 9. 통합 소프트웨어 및 모듈별 빌드 정책

`P_sensor`의 기본 제품 방향은 하나의 통합 프로그램이다. 사용자는 통합 앱 안에서 DAQ, 스테이지 조작, 자동화 오케스트레이션, 실시간 모니터링, 로그를 함께 확인하고 제어할 수 있어야 한다.

단, 각 기능 모듈은 같은 코드베이스를 공유하면서 별도의 단독 프로그램으로도 실행 및 빌드될 수 있어야 한다.

권장 실행 형태는 다음과 같다.

- `P_sensor`: 통합 앱. DAQ, 스테이지, 자동화, 모니터링, 로그를 한 화면에서 조합한다.
- `P_sensor_DAQ`: DAQ/센서 측정 단독 앱.
- `P_sensor_Stage`: 스테이지 수동 조작 및 상태 확인 단독 앱.
- `P_sensor_Automation`: 자동화 레시피 실행 단독 앱.

이때 단독 앱은 독립된 로직 복사본이 아니라, 공통 코어 모듈을 다른 UI 셸에서 조립한 실행 형태로 취급한다.

- DAQ 관련 앱은 모두 `acquisition`, `services.measurement` 계층을 공유한다.
- 스테이지 관련 앱은 모두 `motion` 계층과 동일한 command bridge 인터페이스를 공유한다.
- 자동화 관련 앱은 모두 `automation` 계층의 recipe, runner, safety, storage 모델을 공유한다.
- UI는 `ui` 아래에서 패널 단위로 분리하고, 통합 앱과 단독 앱이 필요한 패널을 조합해서 사용한다.
- `MainWindow`는 장기적으로 모든 기능을 직접 소유하는 파일이 아니라, 패널과 서비스 상태를 조합하는 앱 셸 역할로 축소한다.
- 자동화 실행 UI는 현재 step만 표시하는 수준에 머물지 않고, 전체 진행률, 예상 남은 시간, 예상 종료 시각을 함께 보여주는 상태 모델을 공유한다. 예상 시간은 레시피의 move, settle, measure, disengage 시간을 기준으로 계산하고, 실제 진행 시간이 누적되면 보정할 수 있어야 한다.
- 2026-04-23 기준 자동화 진행률과 예상 시간 계산의 독립 모듈은 `src/p_sensor/automation/progress.py`에 둔다. UI 표시는 후속 통합 대상으로 남기되, 시간 추정과 스냅샷 계산은 UI와 분리된 순수 모듈로 유지한다.

Stage 단독 GUI의 현재 기준은 다음과 같다.

- 실행 진입점은 `python -m p_sensor --profile stage`, `p-sensor-stage`, `scripts/run_stage_app.ps1`로 제공한다.
- 앱 셸은 `src/p_sensor/stage_app.py`, 주 UI는 `src/p_sensor/ui/stage_window.py`에 둔다.
- 장비명은 화면에 명시한다. 현재 기준 표기는 `OPTOSIGMA SHOT-702 / OPTOSIGMA OSMS20-35`다.
- 시작 시 전체화면이 아니라 최대화 상태로 연다. OS 제목 표시줄과 종료 버튼을 유지하고 화면 잘림을 피하기 위해 `showFullScreen()`은 기본값으로 사용하지 않는다.
- 주 기능은 스테이지 구동이므로 이동 패널의 시인성과 조작 면적을 최우선으로 둔다. 연결/설정 영역은 필요한 정보만 남기고 화면 비율을 과도하게 차지하지 않게 한다.
- 스크롤 없이 한 화면에 모든 핵심 기능이 들어가야 한다. 컨트롤 패널은 Stage 선택 수가 바뀌어도 하단이 잘리지 않도록 같은 높이와 폰트 체계를 유지한다.
- 터치스크린 조작을 기본 사용 시나리오에 포함한다. 버튼은 충분히 크게 두고, 축약 라벨보다 오해가 적은 명확한 라벨을 우선한다.
- `터치스크린 온리`는 토글 스위치 형태로 제공하고, 켜진 상태에서는 숫자 입력 필드에 가상 터치 키패드가 뜨게 한다.
- 현재 위치에서 소프트웨어 영점을 설정하는 버튼을 제공한다. 이 기능은 장비를 움직이지 않고 현재 위치를 논리 원점으로 설정한다.
- Stage 선택은 `Stage 1만`, `Stage 2만`, `Stage 1 + Stage 2`를 지원한다. 선택 변경 시 이전 선택의 잔여 레이아웃이나 반쪽 패널 상태가 남지 않도록 전체 컨트롤 패널을 일관된 상태로 재구성한다.
- 이동 방향 안내는 상태 섹션 하위 정보가 아니라 독립 섹션으로 배치한다. 한 Stage만 선택했을 때와 두 Stage를 함께 선택했을 때 모두 한눈에 방향 관계를 볼 수 있도록 코드로 그린 도면을 사용한다.

빌드 정책은 다음을 따른다.

- 통합 앱 빌드는 기본 배포 타깃으로 유지한다.
- DAQ, Stage, Automation 단독 앱은 필요 시 별도 PyInstaller 타깃 또는 빌드 스크립트로 생성한다.
- 단독 앱 빌드를 위해 공통 로직을 복사하거나 별도 패키지로 분기하지 않는다.
- 실행 진입점 차이는 `launcher`, profile, 앱 셸, 빌드 spec 수준에서만 관리한다.
- 공통 설정 스키마는 유지하되, 앱별 기본 설정 파일은 분리할 수 있다.

장비 제어 권한 정책은 다음을 따른다.

- 같은 실제 장비를 동시에 여러 앱이 점유하지 않도록 설계한다.
- 통합 앱 또는 자동화 앱이 실행 중일 때 DAQ와 스테이지는 하나의 실행 컨텍스트가 소유해야 한다.
- 자동화 실행 중에는 수동 DAQ 측정, 수동 AO 출력, 수동 스테이지 이동처럼 자동화 흐름을 깨뜨릴 수 있는 조작을 잠근다.
- 최초 컨택점 자동인식 중에도 수동 스테이지 이동과 자동화 실행은 동시에 허용하지 않는다. 단, 비상 정지와 사용자 중단은 어떤 실행 상태에서도 접근 가능해야 한다.
- 비상 정지, 사용자 중단, 장비 오류, 연결 해제 처리는 통합 앱과 단독 앱에서 같은 서비스/안전 계층을 통해 처리한다.
- 세션 저장 시 DAQ 설정, 스테이지 설정, 자동화 recipe, 실행 앱 형태를 함께 기록해 재현 가능성을 유지한다.

## 10. 2026-04-23 개발 경과 및 GUI 정책 업데이트

현재 개발 경과는 다음 기준으로 정책에 반영한다.

- 현재 저장소 운영 기준 버전은 `v0.4`다.
- `v0.4`는 실 장비 투입 전 프로그램 개발 완료 단계로 정의한다.
- 따라서 `v0.4`까지는 코드, 문서, UI 라벨, 스크립트 기본값이 같은 기준 버전을 가리켜야 한다.

- 자동화 프로토콜은 `step_hold`, `hysteresis`, `speed_dependency`, `fatigue` 네 방향을 기본 시나리오로 둔다.
- 자동화 결과에는 cycle, phase, velocity, 측정 활성 여부, engage/disengage 전후 위치를 함께 기록한다.
- 최초 컨택점 자동인식은 `src/p_sensor/automation/contact.py`, 진행률/예상 시간 계산은 `src/p_sensor/automation/progress.py`에 독립 모듈로 둔다.
- 이전 하드웨어 오해를 줄이기 위해 active 코드와 스크립트의 명칭은 현재 장비 기준인 `SHOT-702`/`OSMS20-35` 또는 중립적인 `stage`, `shot_series` 계열로 유지한다.
- 리니어 스테이지 시뮬레이션은 개발 기본 경로로 유지한다. `config/stage_simulated.example.json`과 `SimulatedShotController`를 사용해 실제 장비 없이 UI, CLI, automation smoke를 검증할 수 있어야 한다.
- `scripts/check_stage.ps1`와 `scripts/run_automation_smoke.ps1`의 기본 모션 설정은 시뮬레이션을 우선하고, 실장비 구동은 `dev_local/config/...local.json`을 명시한 경우로 제한한다.
- 2026-04-23 기준 코드 검증은 `ruff`와 `pytest` 전체 테스트 통과를 기준으로 기록한다.

통합 GUI 정책은 다음을 우선한다.

- 메인 앱은 탭 전환 없이 한 화면에서 DAQ, Stage, Safety, Protocol, Channels, Results, Log에 접근하는 고밀도 Cockpit 구조를 기본으로 한다.
- 우측 Cockpit은 `Run`, `Motion`, `Protocol`, `Channels` 섹션으로 구성하고, 핵심 조작 버튼과 상태값을 숨기지 않는다.
- 좌측 영역은 plot, Live Monitor, Log, Results를 동시에 보여준다. 결과와 로그는 실행 중 서로 가려지지 않아야 한다.
- 스크롤은 사용하지 않거나 최소화한다. 불가피한 경우에도 접속, 시작/중단, 비상 정지, 현재 위치, 실행 상태는 첫 화면에 남긴다.
- padding, margin, group spacing은 정보 밀도를 높이는 방향으로 최소화한다. 단, `QGroupBox` 제목, 라벨, 버튼 텍스트가 잘리거나 서로 겹치면 레이아웃 결함으로 본다.
- 버튼은 텍스트가 보이는 최소 크기를 기준으로 하며, 긴 경로와 설정명은 짧은 표시명과 tooltip으로 처리한다.
- 빈 여백은 장식으로 남기지 않고 sequence preview, progress/ETA, 상태 알림, 결과 테이블, 자동화 로그 같은 정보 표출에 재배정한다.
- Live Monitor는 필요한 높이 이상으로 확장하지 않는다. 모니터링 값보다 실행 판단에 중요한 결과/로그/프로토콜 정보가 우선 공간을 가져야 한다.
- 카드나 그룹을 과도하게 중첩하지 않는다. 패널 분리는 코드 구조의 책임 분리이고, 화면에서는 사용자가 한 번에 판단할 수 있는 밀도와 정렬을 우선한다.
- GUI 변경 후에는 label clipping, 버튼 overlap, 불필요한 blank area, 동적 텍스트로 인한 layout jump를 필수 점검 항목으로 둔다.

## 11. 차기 통합 UI 배치 개선 정책

2026-04-24 기준 차기 통합 UI는 기존 기능을 단순히 나열하지 않고, 측정 준비, 수동 조정, 자동화 실행 상태를 한 화면에서 순서 있게 판단할 수 있는 구조로 재배치한다. 이 항목은 구현 전 배치 정책이며, 세부 구현 중에는 기존 동작을 유지할 기능과 제거할 기능을 별도로 검토한다.

상단 상태 영역은 장비 오케스트레이션 readiness를 신호등형 단계 표시로 보여준다. 단계는 `DAQ 장치 연결 -> DAQ backend 선택 -> DAQ 신호 테스트 -> Stage 장치 연결 -> Stage backend 선택 -> Stage 신호 테스트 -> 실험 결과 저장 폴더 지정/생성` 순서를 기본으로 한다. 각 단계는 `Ready`, `Warning`, `Blocked`, `Pending` 상태를 가지며, 앞 단계가 준비되지 않은 경우 뒤 단계는 대기 상태로 표시해 측정 전 확인 순서를 간접적으로 드러낸다. `Live Monitor`처럼 저장이 필요 없는 기능은 저장 폴더 readiness와 분리한다.

메인 화면은 상단 readiness 영역 아래에 좌측 측정 workspace와 우측 status/log 영역을 배치하고, 외부 가로 비율은 `8:2`를 기본으로 한다. 좌측 측정 workspace 내부는 `DAQ:Stage = 4:4` 2열 그리드로 나누어 기존 `4:4:2` 정보 밀도를 유지한다. 창이 좁아져도 섹션을 재배치하기보다 전체 작업대가 비율을 유지한 채 축소되는 느낌을 우선한다. 극단적으로 좁은 화면에서는 최소 기준 폭, scale down, horizontal scroll 허용 여부를 구현 단계에서 결정한다.

DAQ 섹션과 Stage 섹션의 상단 plot은 같은 크기로 유지하고, plot widget의 기본 비율은 `가로:세로 = 2:1`로 고정한다. plot 비율은 사용자 슬라이더로 조정하지 않는다. DAQ plot 아래에는 실시간 측정값을 보여주는 digital meter를 유지한다. 각 표시 모듈에는 compact한 limit warning toggle을 둔다. toggle이 꺼져 있으면 값은 중립적으로 표시하고, toggle이 켜진 경우에만 사용자가 설정한 lower/upper limit 또는 baseline rule에 따라 `OK`, `High`, `Low`, `No rule` 상태를 표시한다.

DAQ channel settings는 좌측 측정 workspace의 하단 행에 두고, DAQ 열과 Stage 열을 함께 span해 빈 공간을 활용한다. 이때 DAQ 영역은 왼쪽 열의 DAQ plot/live/control과 하단 channel settings가 이어지는 `ㄴ` 형태의 외곽으로 읽히게 한다. Channel settings 내부의 AI/AO 설정은 세로로 쌓지 않고 가로로 나란히 배치하며, 표 여백과 행 높이를 줄여 하단 strip처럼 compact하게 유지한다. 테이블 행 높이는 균일해야 하고, combo/spin 같은 cell widget 때문에 특정 셀만 더 높아지지 않아야 한다. 하단 strip에서는 가로 스크롤이 생기지 않도록 컬럼 폭을 컨테이너 안에서 stretch하거나 축약한다. 포함 항목은 채널 enable/disable, 물리 채널 선택, 측정 단위, 변환식, 보정값, 저항 계산 관련 파라미터, limit warning 설정, channel config 저장/불러오기다. AO의 Min/Max 범위가 바뀌면 Initial/Setpoint 값은 새 범위 안으로 즉시 clamp해 stale 값 때문에 설정 적용이나 측정 시작이 실패하지 않게 한다. plot 표시 여부와 digital meter 표시 여부는 채널 enable/disable과 분리하지 않는다. enabled 채널은 측정 대상이며 plot과 digital meter에 표시되고, disabled 채널은 측정과 표시에서 제외한다.

프로그램 기본 DAQ 구성은 AI 1개와 AO 1개로 시작한다. 단, channel settings에서 물리 채널을 추가 선택하거나 config를 확장해 AI/AO 채널 수를 늘리는 기능은 유지한다. AI-only 또는 automation 전용 profile은 AO를 숨기되, 기본 AI 채널 수는 1개로 시작한다.

DAQ에는 파일 기록 없이 실시간 plot과 digital meter만 동작하는 `Live Monitor` 모드를 둔다. 이 모드는 스테이지를 수동으로 조정하면서 전압 또는 저항 변화 순간을 확인하는 용도이며, 저장 폴더 readiness를 요구하지 않는다. 기록이 필요한 측정은 별도 `Record Measurement` 흐름으로 두고, 저장 경로와 세션 조건이 준비된 경우에만 시작한다.

NI DAQ는 serial `COM` 포트가 아니라 NI-DAQmx 장치명(`cDAQ1`, `Dev1` 등)으로 식별한다. 메인 DAQ Control은 backend 선택과 같은 방식으로 `DAQ Device` 콤보와 감지 목록 새로고침을 제공해야 하며, USB 재연결 후 장치명이 바뀐 경우 사용자가 목록에서 현재 장치를 선택해 채널 물리명과 runtime config가 함께 갱신되어야 한다.

Live Monitor의 AI/AO 표시 영역은 채널 수에 따라 동적으로 배치한다. 기본 구성처럼 AI 1개와 AO 1개만 표시되는 경우에는 `AI Live`와 `AO Live`를 가로로 나란히 배치해 세로 공간을 절약한다. AI 또는 AO가 여러 개로 확장된 경우에는 기존처럼 카드가 충분히 보이는 세로/그리드형 배치를 사용한다.

Stage 섹션의 상단에는 스테이지 위치와 이동 경로를 보여주는 plot을 둔다. Stage 1은 Z축, Stage 2는 X축이라는 기존 정책을 따른다. 기본 plot은 시계열이며, 정지 중 실제 시간이 아니라 stage가 움직여 위치 변화가 들어온 시간만 `Move time`으로 누적한다. Stage 1만 움직이면 `Z position vs move time`, Stage 2만 움직이면 `X position vs move time`을 표시한다. X/Z 위치 샘플이 모두 충분히 확보되고 3D 런타임이 사용 가능하면 `X/Z/move time` 기반 3D trajectory로 전환한다. 3D 의존성이 없거나 샘플이 부족한 경우에는 2D 시계열 fallback이 항상 보여야 하며, plot stack이나 내부 widget의 폭이 0으로 잡히지 않도록 크기 동기화를 유지한다.

Stage plot 아래에는 position dashboard, manual motion controls, soft limit strip, orchestration control module을 배치한다. position dashboard는 현재 X/Z 위치, 이동 상태, 선택된 manual axis, contact calibration 상태, 마지막 위치 갱신 시각처럼 현재 상태 확인만 담당한다. Contact calibration 진입 버튼은 soft limit이나 recipe 실행 설정 안에 넣지 않고, contact 상태와 같은 dashboard 영역에 배치한다. 목표 위치는 dashboard에서 제외하고 manual motion controls의 absolute move 입력과 통합한다. Manual motion controls는 `Backend` 선택을 DAQ backend 선택과 같은 콤보박스 방식으로 제공하며, 별도 stage config 파일 load 버튼은 메인 화면에 두지 않는다. 새 stage backend나 장치를 추가할 때는 코드의 backend mapping을 확장한다. `SW 0`은 현재 세션의 소프트웨어 영점으로 이동하는 의미로, `HW Home`은 장치 컨트롤러의 하드웨어 원점 복귀 명령으로 명확히 구분해 표시한다.

Contact calibration은 readiness 체크박스나 매번 실행되는 contact detection이 아니라, 최초 기준점을 정하는 반자동 보정 워크플로로 취급한다. 메인 화면에는 `Contact Cal.`, 마지막 contact point, `Calibrated/Not set/Stale` 상태만 compact하게 표시하고, 실제 절차는 단계형 popup 또는 wizard에서 수행한다. 사용자는 먼저 Stage 1/Z축을 충분히 위로 올린 뒤 육안으로 probe를 contact 또는 contact 근접 위치까지 내린다. 이후 자동 calibration을 실행하면 프로그램은 기본 `1 mm` 또는 사용자 설정 거리 이내에서 Stage 1/Z축을 가장 작은 step 또는 설정된 micro-step만큼 하강시키며 DAQ 값을 수집한다.

Contact calibration popup은 선택 DAQ 채널의 live time plot과 `Z position` 대비 DAQ 값 scan graph를 함께 표시한다. DAQ monitor/record가 이미 실행 중이면 그 스트림을 사용하고, 실행 중이 아니면 wizard 전용 임시 DAQ preview를 시작해 내부 live plot만 갱신한 뒤 wizard 종료 시 정리한다. 샘플이 아직 없을 때는 wizard 내부 live plot 상태로 대기/오류를 보여준다. Stage가 연결되지 않은 경우에도 wizard는 열어 live DAQ 상태와 절차를 확인할 수 있게 하되, 실제 `Auto Scan`은 Stage 1/Z 연결 전에는 비활성화한다. 사용자는 live plot으로 DAQ monitor/record 또는 임시 DAQ preview가 정상 동작하고 신호가 안정적인지 먼저 확인한 뒤 scan graph에서 threshold crossing과 선택 contact point를 판단한다. 프로그램은 baseline 대비 변화량, 변화율, noise 수준, 연속 조건을 사용해 nominal contact point 후보를 추천한다. 단, 최종 nominal contact point는 사용자가 그래프에서 직접 클릭해 선택하거나 추천점을 적용하는 방식으로 확정한다. 적용된 위치는 기계 원점이 아니라 측정 시작 nominal contact point이며, 세션 또는 보정 메타데이터에 기록한다. 오케스트레이션 recipe에는 매번 calibration을 수행하는 기능보다 기존 contact point를 실행 전 점검할지 여부를 옵션으로 둔다.

DAQ와 Stage 섹션의 핵심 UI를 먼저 배치한 뒤, Stage 섹션에서 확보된 공간에 orchestration control module을 둔다. 이 모듈은 recipe 선택/로드, recipe wizard, session reopen, run/stop, motion bridge 상태, contact/check 요약, progress 요약을 compact하게 다룬다. 실행 버튼과 recipe 로드 같은 조작은 우측 log/status 영역에 두지 않는다.

우측 status/log 영역은 위아래로 나누고 splitter로 사용자가 높이를 조정할 수 있게 한다. 상단은 `Recipe Steps` 영역으로, orchestration recipe step list와 진행 footer만 표시한다. recipe 로드, helper, run/stop 같은 조작 버튼은 Stage 섹션의 orchestration control module에 둔다. Step list는 스크롤 가능한 목록으로 표시하고, 현재 수행 중인 단계, 완료 단계, 대기 단계, 실패 단계를 색상으로 구분한다. step list 아래에는 고정 footer를 두어 `Elapsed 00:12:34 | Left 00:04:20 | ETA 15:42` 형식의 compact time strip과 `Progress 65%` 및 progress bar를 항상 보이게 한다. 하단은 `System Log`로 두고 timestamp, level, source, message 중심의 디버깅용 system echo log로 유지한다.

## 12. 차기 UI 기능 유지, 흡수, 제거 결정

2026-04-24 기준 차기 UI 재배치에서 기존 기능은 다음 기준으로 유지 여부를 결정한다. 이 항목은 코드 제거 지시가 아니라 구현 방향 기록이며, 실제 삭제 또는 이관은 새 UI 구성과 동작 검증 후 수행한다.

`Contact Detection` 체크 UI는 메인 화면과 protocol panel에서 제거하거나 흡수한다. 기존 자동 감지 로직은 버리지 않고 `Contact Calibration Wizard` 안에서 micro-step scan, 변화량 분석, 추천 nominal contact point 계산에 재사용한다. Contact 관련 입력값인 `stage_axis`, `channel_index`, `scan_speed`, `scan_step`, `max_travel`, `delta_resistance_threshold`, `baseline_duration`, `stable_duration`, `use_as_zero`는 메인 화면 상시 조작값이 아니라 recipe 또는 calibration/check wizard에서 지정되는 설정값으로 취급한다. 메인 화면에는 contact 상태만 `Not set`, `Calibrated`, `Stale`, `Check required`처럼 요약 표시한다.

`Results` 패널의 결과 테이블은 차기 통합 UI에서 상시 영역으로 유지하지 않는다. 자동화 결과의 원본은 CSV 파일과 세션 manifest를 기준으로 확인한다. 실시간 판단은 DAQ live plot, digital meter, Stage plot, orchestration step list가 담당한다. 대신 CSV 저장 주기 설정은 필요하므로 `Record Measurement` 설정 또는 orchestration control module에 `CSV save interval` 같은 시간 기반 저장 주기 입력을 추가한다.

`Recipe Helper`는 유지하되 wizard 형태로 재구성한다. 사용자는 정책문서에 정의된 4가지 측정 방식인 `step_hold`, `hysteresis`, `speed_dependency`, `fatigue` 중 하나를 선택하고, wizard가 필요한 입력값을 단계적으로 받아 자동화 recipe 파일을 생성해야 한다. 기존 protocol panel의 빠른 입력 UI는 wizard의 내부 단계 또는 advanced 설정으로 흡수한다.

AO 기능은 독립 실행 목적의 주요 기능으로 보지 않는다. 차기 통합 UI에서는 DAQ 섹션의 설정값 일부로 취급하고, 기본 운용은 `AI + optional AO`로 둔다. `AI only` 운용은 가능하지만 `AO only` 운용은 제품 흐름에서 제외한다. AO overlay 또는 AO 출력값 표시는 AI 측정 흐름을 보조하는 설정으로만 남긴다.

`Start Mark`와 `Stop Mark` 기능은 유지한다. 이 기능은 DAQ plot과 Stage plot 양쪽에서 수동 조정 또는 실험 중 의미 있는 순간을 표시하는 annotation/marker 기능으로 제공한다. marker는 CSV 또는 세션 메타데이터에 저장할 수 있어야 하며, 최소한 plot 상에서 시각적으로 확인 가능해야 한다.

기존 `SafetyPanel`은 독립된 큰 패널로 유지하기보다 readiness bar, Stage 섹션, orchestration control module에 기능을 분산 흡수한다. 안전 정보는 단순 표시보다 버튼 활성 조건, 실행 차단 사유, 상태 색상과 직접 연결되어야 한다. origin/home 상태, hold/free 상태, recovery required 상태, soft limit 상태는 Stage 섹션과 readiness에 노출한다. 비상 정지와 사용자 중단은 어떤 실행 상태에서도 접근 가능해야 한다.

Stage soft limit은 사용자가 UI에서 직접 설정할 수 있어야 한다. 하드웨어 또는 backend mapping의 물리 한계는 절대 상한으로 두고, 사용자는 그보다 좁은 `Min position`, `Max position`, `Enable soft limit` 값을 지정해 소프트웨어 락을 걸 수 있다. 이 UI는 `Soft limit | Min | Max` 한 줄 strip으로 compact하게 유지하고, contact calibration 버튼과 섞지 않는다. 이 제한은 manual jog, absolute move, contact calibration scan, orchestration recipe target 모두에 적용한다. recipe target 또는 수동 이동 명령이 soft limit을 벗어나면 실행 전 차단하고, jog 중 한계에 도달하면 추가 이동을 막거나 즉시 중단한다. `Min >= Max`처럼 soft limit 자체가 유효하지 않은 경우에는 Run 버튼을 비활성화하고 시작 전 사용자 오류로 처리하며, UI 밖으로 예외가 전파되어서는 안 된다.

## 13. 메뉴바 Tools 및 Advanced 기능 재정리 방향

2026-04-24 기준 메뉴바로 이동한 `Setup`, `Contact Details`, `Protocol`, `Channels`, `Annotations` 항목은 아직 최종 GUI 정책에 맞게 재구성된 기능으로 보지 않는다. 메뉴바는 메인 cockpit에서 숨겨진 핵심 조작을 대신하는 위치가 아니라, 메인 화면의 고밀도 배치를 해치지 않으면서 상세 설정, wizard, manager, 진단 화면으로 들어가는 보조 진입점으로 사용한다. 따라서 메뉴 항목은 안내문 placeholder나 기존 위젯 재배치가 아니라 실제 목적이 명확한 dialog 또는 wizard를 열어야 한다.

메뉴바 기능을 구현할 때는 같은 설정 위젯을 메인 화면과 메뉴 dialog 사이에서 re-parenting하지 않는다. 한 위젯을 두 위치에서 재사용하면 메인 화면의 컨트롤이 사라지거나 상태 동기화가 꼬일 수 있으므로, dialog는 현재 앱 상태를 읽어 별도 form/model로 표시하고 `Apply`, `Save`, `Load`, `Cancel` 같은 명시적 commit 동작으로 메인 상태에 반영한다. 메뉴 dialog를 닫아도 DAQ, Stage, readiness, orchestration 상태가 바뀌지 않아야 한다.

`Setup` 메뉴는 메인 화면의 DAQ Control과 Stage Reference를 복제하는 편집 화면으로 만들지 않는다. 기본 역할은 현재 backend, chassis, slot, sampling, export folder, stage config, soft limit, readiness 차단 사유를 한 번에 확인하는 `Setup Summary / Diagnostics` dialog다. 여기에는 config 검증, 저장 폴더 접근 확인, DAQ backend 테스트, Stage config 경로 확인, 현재 세션 설정 저장/불러오기 같은 진단성 기능을 배치한다. 사용자가 값을 자주 바꾸는 backend, slot, sampling, export folder는 계속 DAQ 섹션에 남긴다.

`Contact Details` 메뉴는 raw contact parameter 입력 폼으로 유지하지 않는다. 기존 contact detection 관련 값은 `Contact Calibration Wizard`와 recipe/check 옵션으로 흡수한다. 메뉴 항목은 `Contact Calibration` wizard를 여는 진입점이 되어야 하며, wizard 안에서 scan axis, channel, step, max travel, threshold, baseline, stable 조건을 단계적으로 설정하고 그래프 기반 추천점과 사용자 선택점을 확정한다. 메인 화면에는 마지막 contact point와 `Not set`, `Calibrated`, `Stale`, `Check required` 같은 요약 상태만 남긴다.

`Protocol` 메뉴는 기존 `ProtocolPanel`의 빠른 입력 화면을 그대로 노출하는 방향보다 `Recipe Wizard`로 통합한다. 사용자는 `step_hold`, `hysteresis`, `speed_dependency`, `fatigue` 중 하나를 선택하고, wizard가 필요한 입력값과 contact check 여부, motion/DAQ 조건, 저장 조건을 순서대로 받는다. 생성 결과는 recipe JSON preview, validation result, expected duration, step list로 확인한 뒤 적용한다. 낮은 수준의 protocol parameter 편집은 advanced JSON editor 또는 expert mode로 분리하고, 일반 메뉴 동선의 기본값으로 두지 않는다.

`Channels` 메뉴는 메인 DAQ 섹션의 channel table을 대체하지 않는다. 메인 화면에는 enabled 채널과 핵심 설정을 유지하고, 메뉴 항목은 `Channel Config Manager`로 재정의한다. 이 manager는 channel config 저장/불러오기, AI/AO 채널 추가와 삭제, 여러 물리 채널 일괄 선택, 이름/색상/단위/변환식 preset 적용, limit warning preset 적용, config diff/validation을 담당한다. 프로그램 기본값은 AI 1개와 AO 1개로 시작하지만, 이 manager와 channel settings를 통해 채널 수를 확장할 수 있어야 한다.

`Annotations` 메뉴는 DAQ plot과 Stage plot의 `Start Mark`/`Stop Mark` 버튼을 대체하지 않는다. plot 위의 빠른 mark 기능은 유지하고, 메뉴 항목은 `Marker / Annotation Manager`로 만든다. 이 manager는 DAQ marker와 Stage marker를 함께 보여주고, marker 이름 변경, 삭제, 색상 변경, CSV 또는 session metadata 저장 여부, marker list export를 담당한다. 자동화 실행 중 생성된 step marker와 사용자가 찍은 manual marker는 구분해서 표시한다.

메뉴바 항목 이름도 실제 동작과 맞춰 조정한다. 예를 들어 `Tools > Setup`, `Tools > Contact Calibration`, `Tools > Recipe Wizard`, `Tools > Channel Config Manager`, `Tools > Marker Manager`처럼 사용자가 메뉴명만 보고 결과를 예측할 수 있게 한다. 아직 구현되지 않은 항목은 placeholder dialog로 열어두기보다 disabled 상태와 tooltip으로 예정 기능을 명확히 표시하거나, 최소 기능을 먼저 구현한 뒤 활성화한다.

구현 우선순위는 다음 순서로 둔다. 첫째, 현재 `detail_tool_window`의 placeholder와 widget re-parenting 의존을 제거하고 메뉴별 독립 dialog/wizard 구조로 분리한다. 둘째, `Recipe Wizard`와 `Contact Calibration Wizard`를 메뉴와 메인 화면 버튼에서 동일하게 호출하도록 연결한다. 셋째, `Channel Config Manager`에서 AI/AO 채널 확장과 config save/load를 제공한다. 넷째, `Marker Manager`에서 DAQ/Stage marker 목록과 저장 정책을 관리한다. 다섯째, `Setup Summary / Diagnostics`로 readiness 차단 사유와 장비 테스트 결과를 모아 보여준다.

메뉴바 기능을 수정한 뒤에는 테스트에서 최소한 다음을 확인한다. 각 메뉴 action이 의도한 dialog를 열고, dialog를 열고 닫아도 메인 화면 위젯이 사라지지 않으며, `Apply` 전에는 메인 config가 변하지 않고, `Apply` 후에는 readiness와 summary가 갱신되어야 한다. 또한 AI 1/AO 1 기본 구성에서도 manager가 채널을 확장할 수 있고, 확장된 config를 저장/불러온 뒤 같은 채널 수와 물리 채널 매핑이 유지되어야 한다. 주요 GUI 재배치 뒤에는 simulated DAQ/stage 기반 가상 조작 시나리오를 5회 이상 반복해 live monitor, record, stage move, automation, guard path에서 치명 예외나 목적에 맞지 않는 블로킹 오류가 없는지 확인한다.

## 14. 2026-04-24 개발 진행 정리 및 현행 UI 운영 기준

2026-04-24 작업 결과는 차기 정책이 아니라 현재 통합 앱에 반영된 운영 기준으로 취급한다. 이후 UI를 더 조정하더라도 아래 기준을 깨뜨리지 않는 방향으로 변경한다.

측정 workspace는 좌측 `DAQ`와 우측 `Stage`를 같은 폭으로 두고, 하단 `Channels` 영역은 두 열을 함께 span하는 구조로 유지한다. DAQ 섹션은 왼쪽 plot/live/control과 하단 channel shelf가 이어지는 `ㄴ` 형태의 경계로 읽히게 하며, channel shelf는 AI/AO 테이블을 가로 배치하고 횡스크롤 없이 보이도록 한다. 채널 테이블 행 높이는 균일해야 하며, combo/spin cell widget 때문에 특정 셀만 커지면 레이아웃 결함으로 본다.

DAQ 장치 선택은 NI-DAQmx 장치명 기준으로 한다. NI DAQ는 `COM` 포트를 쓰지 않으므로 `DAQ Device` 콤보와 `Devices` 새로고침으로 `cDAQ1`, `Dev1` 같은 장치명을 선택한다. 사용자가 USB를 다시 연결해 장치명이 바뀐 경우 현재 장치명을 고르면 물리 채널명과 runtime config가 함께 갱신되어야 한다. 이미 연결된 controller가 이전 장치명으로 만들어졌다면 Monitor, Record, AO 적용 전 현재 UI config와 다른 controller를 재사용하지 않고 재연결한다.

Stage 수동 제어는 stage config load 버튼 없이 backend 콤보와 runtime `Port` 콤보로 운영한다. 새 stage 장치나 backend 추가가 필요하면 UI에서 임의 config 파일을 고르는 방식보다 코드의 backend mapping을 확장한다. USB-serial 연결 순서에 따라 `COM` 번호가 바뀔 수 있으므로 SHOT-702 실장비는 Stage `Port` 목록 새로고침 후 현재 포트를 선택한다. 시뮬레이션 backend는 serial port를 사용하지 않으며 `SIM`으로 표시한다.

Stage 섹션은 세로 공간을 아껴 하단 `Channels` 영역을 밀어내지 않아야 한다. Stage manual controls는 `Backend/Port`, `Axis/Status/Position`, `Step`, `Abs` 중심의 compact grid로 유지하고, position dashboard는 한 줄 상태 strip으로 유지한다. Soft limit strip은 `Origin Confirmed`, `Soft limit`, `Min`, `Max`를 한 줄에 둔다. Manual jog 또는 absolute move가 soft limit에 막히는 경우는 정상 safety guard이므로 modal critical dialog로 조작 흐름을 끊지 않고 Stage 상태와 system log에 non-blocking으로 표시한다. `Origin Confirmed`는 실제 하드웨어 automation 전 현재 기준 위치가 유효하다는 사용자 확인이며, 실장비 설정에서는 체크/해제가 가능해야 한다. 시뮬레이션에서는 `Origin Confirmed (Sim)`으로 표시하고 자동 체크/비활성화한다.

Stage plot은 Stage 1/Z와 Stage 2/X 정책을 따른다. 기본 plot은 실제 wall-clock이 아니라 stage가 움직여 위치 변화가 들어온 시간만 누적한 `Move time` 시계열이다. X/Z 위치 샘플이 모두 확보되고 3D 런타임이 가능하면 3D trajectory로 전환할 수 있지만, 3D가 없거나 샘플이 부족하면 2D fallback이 항상 보여야 한다. Stage plot이 수정된 뒤 그래프가 비거나 widget 폭/높이가 0이 되는 상태는 회귀로 본다.

DAQ plot과 Stage plot의 빠른 mark 기능은 plot header에 둔다. 두 plot 모두 `Marks N`, `Start Mark`, `Stop Mark`를 같은 패턴으로 제공한다. DAQ mark는 실행 중 시간 구간 highlight를 만들고, Stage mark는 현재 stage plot point에 marker를 추가한다. Stage mark를 추가하면 Stage header의 `Marks N`도 즉시 갱신되어야 한다. 메뉴의 future `Marker Manager`는 이 빠른 mark 버튼을 대체하지 않고 목록 관리와 저장 정책을 담당한다.

Contact Calibration Wizard는 초보자가 절차를 따라갈 수 있도록 안내, scan settings, live DAQ plot, Z-position scan graph를 함께 제공한다. Stage가 연결되지 않아도 wizard는 열려야 하지만 Auto Scan은 Stage 1/Z 연결 전에는 비활성화한다. DAQ Monitor 또는 Record가 이미 실행 중이면 wizard는 그 스트림을 사용한다. 둘 다 실행 중이 아니면 메인 Live Monitor를 켜지 않고 wizard 전용 임시 DAQ preview를 시작해 wizard 내부 plot만 갱신하고, wizard 종료 시 반드시 정리한다. 따라서 wizard를 닫은 뒤 사용자가 명시적으로 켜지 않은 메인 DAQ monitoring이 남아 있으면 회귀로 본다.

오케스트레이션 컨트롤은 Stage 섹션 안에 두고, 우측 status/log 영역은 `Recipe Steps`와 `System Log`만 유지한다. Recipe load, helper, session reopen, Run/Stop 같은 조작은 우측 로그 영역에 두지 않는다. Stage 섹션 하단의 orchestration 상태 영역은 세로로 라벨을 쌓지 않고 compact row로 구성한다. 상태 줄은 `Automation status / Motion / Contact`, 실행 줄은 `Recipe status / Run / Stop`처럼 가로 배치해 Stage 섹션 높이를 과도하게 늘리지 않는다.

`Recipe Steps`는 실행 중 step을 다른 음영으로 표시해야 한다. `step_started` 또는 `phase_started` 상태에서 현재 step row만 highlight하고, `step_completed`가 들어와 completed count가 올라가면 해당 row의 highlight를 제거한다. 완료, 대기, 진행 텍스트 표시는 보조 정보이며, 진행 중 단계는 시각적으로도 구분되어야 한다.

자동화 안전 조건은 사용자가 해결할 수 있는 위치에 노출되어야 한다. `Origin Pending`처럼 Run을 막는 조건은 숨겨진 SafetyPanel에만 두지 않고 Stage 섹션의 visible control과 연결한다. Soft limit 오류, contact motion requirement, origin confirmation requirement는 Run 버튼 활성 조건과 scenario hint에 같은 의미로 반영되어야 한다. 시뮬레이션 경로는 하드웨어 origin 확인 때문에 막히지 않아야 하고, 실장비 경로는 `Origin Confirmed`가 해제되면 다시 `Origin Pending`으로 돌아가야 한다.

Recipe Wizard와 Contact Calibration Wizard는 화면 밖으로 하단이 밀려 사용자가 완료/닫기 조작을 못 하는 상태가 되면 안 된다. wizard류 화면은 현재 창/화면 높이에 맞는 최대 높이와 내부 스크롤 또는 compact layout을 가져야 하며, 핵심 버튼은 항상 접근 가능해야 한다.

2026-04-25 기준 현행 cockpit 레이아웃은 이전보다 조밀해졌지만, 아직 목표 밀도에 도달한 상태로 보지 않는다. 특히 `DAQ Control`, `Live Monitor`, `Channels`, `Stage manual controls`, `Position Dashboard`, `Recipe Steps / System Log` 주변에는 여전히 줄일 수 있는 padding, group title 여백, row spacing, height buffer가 남아 있다고 본다. 이후 레이아웃 작업은 "플롯을 제외한 보조 섹션을 먼저 더 압축하고, 그로 확보한 공간을 두 플롯에 동일 비율로 재배분한다"를 기본 원칙으로 삼는다.

세부 개선 방향은 다음을 따른다. 첫째, `DAQ Control`과 Stage 수동 제어는 버튼/입력 높이, row spacing, group 내부 margin을 더 줄여도 라벨 클리핑이나 오조작 위험이 없는지 확인하면서 고밀도 strip에 가깝게 다듬는다. 둘째, `Live Monitor`와 `Channels`는 카드/테이블 내부 모듈 높이는 유지하되 group 자체의 title 오버헤드와 하단 buffer를 더 줄인다. 셋째, `AI 1/AO 1` 또는 `AI 2/AO 2`까지는 상위 workspace와 내부 모듈 모두에서 불필요한 스크롤이 생기지 않아야 하며, 채널 확장 시에만 section 내부 스크롤과 workspace 스크롤을 허용한다. 넷째, `DAQ plot`과 `Stage plot`은 항상 같은 크기와 같은 비율을 유지한 채 가능한 한 크게 보여야 하며, 보조 섹션의 여백이 다시 늘어나 두 플롯을 줄여서는 안 된다.

따라서 이후 UI 압축 작업의 완료 기준은 단순히 테스트 통과가 아니라, 실측 화면 캡처 기준으로도 빈 띠처럼 보이는 잉여 여백이 줄고 플롯 가시성이 체감상 개선되는지까지 포함한다. 테스트는 기존 `pytest`/`ruff` 기준을 유지하되, 캡처 기반 점검에서 `2채널 기본 구성 무스크롤`, `4채널 확장 시 조건부 스크롤`, `두 플롯 동일 크기 유지`, `보조 섹션의 불필요한 blank area 축소`를 함께 확인한다.

검증 기준은 `ruff`와 `pytest dev_local/tests` 전체 통과를 유지한다. 2026-04-24 작업 종료 기준 전체 테스트는 `146 passed`까지 확인했다. UI 배치 변경 뒤에는 최소한 main window control, profile layout, highlight marker, contact calibration, compact stage panel 테스트를 함께 확인한다. 기본 automation smoke recipe는 simulated DAQ 신호가 stage 위치와 연동되지 않는 점을 고려해 contact detection을 켜지 않는다. Contact detection 회귀는 별도 단위/통합 테스트와 Contact Calibration Wizard 경로에서 확인한다. GUI 변경 뒤에는 simulated DAQ/stage 기반 랜덤 조작 시나리오를 5회 이상 반복해 monitor, record, stage jog, contact wizard, automation run, marker 조작 중 modal 오류나 예기치 않은 runtime 예외가 없는지 확인한다.
