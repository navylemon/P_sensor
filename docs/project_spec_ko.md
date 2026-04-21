# 저항 기반 센서 측정 GUI 프로그램 명세 및 진행 현황

최종 갱신: 2026-04-20

## 1. 문서 목적

이 문서는 현재 저장소에 구현된 `P_sensor` 애플리케이션의 범위, 구조, 구현 상태, 남은 과제를 정리한 현행 기준 문서다. 초기 요구사항 문서 역할뿐 아니라 실제 코드와 문서가 어긋나지 않도록 유지하는 기준 문서로 사용한다.

## 2. 프로젝트 개요

- 대상 하드웨어: `NI cDAQ-9174` + `NI 9234`
- 목표 신호: 휘스톤 브리지 기반 저항 센서의 출력 전압
- 계산 결과: 전압과 환산 저항값
- 기본 구성: 8채널, 2모듈, 4포트씩
- 확장 목표: 최대 16채널
- 실행 환경: `Windows 10/11`, `Python >=3.12,<3.14`
- GUI 스택: `PySide6`, `pyqtgraph`
- DAQ 제어: `nidaqmx`
- 확장 방향: 리니어 스테이지 연동 자동화와 단계형 실험 실행
- 자동화 기준 스테이지/컨트롤러: `OPTOSIGMA OSMS20-35` + `OPTOSIGMA SHOT-702`

## 3. 현재 구현 범위

### 3.1 구현 완료

- `simulation` 백엔드
- `ni` 백엔드의 연속 취득 연결 로직
- 활성 채널 기준 측정 루프와 백그라운드 취득 스레드
- `MeasurementService` 기반 측정 창(window) 수집과 집계
- 전압-저항 환산 로직
- 채널별 상태(`normal`, `warning`, `error`) 판정
- 실시간 모듈 카드 표시
- 저항/전압 듀얼 표시 그래프
- 그래프 범위 선택(`10 s`, `1 min`, `5 min`, `All`)
- 채널별 그래프 표시 On/Off
- 세션 라벨 기반 CSV 저장
- 설정 JSON 저장/불러오기
- 창 geometry 및 splitter 상태 복원
- 기본 테스트 실행 환경
- 자동화 레시피 로드와 백그라운드 실행
- 변위 시작점/종료점/step 크기 기반 레시피 생성 헬퍼
- 자동화 세션 폴더, `session_manifest.json`, `step_summary.csv`, `measurement_XXXX.csv` 저장
- `OPTOSIGMA SHOT-702` 기반 리니어 스테이지 설정과 SHOT 계열 명령 브리지
- `OPTOSIGMA OSMS20-35` 변위 기준 `mm -> pulse` 환산 이동
- `SHOT-702`/`SHOT-102` 수동 점검 CLI와 PowerShell 실행 스크립트
- 실장비 기준 SHOT 계열 연결, status 조회, 상대 이동, 방향키 jog, origin 복귀 검증
- 자동화 step 결과와 `step_summary.csv`에 모션 위치(`position_before_mm`, `position_after_engage_mm`, `position_after_disengage_mm`) 기록
- 자동화 안전 정책(`AutomationSafetyPolicy`) 기반 목표 변위와 실제 위치 소프트 리밋 검증
- 자동화 smoke CLI와 `0.5 mm -> 측정 창 -> 0.0 mm` 실장비 오케스트레이션 검증

### 3.2 부분 구현

- NI 장비 사용 가능 여부 확인과 연결 오류 메시지는 구현되어 있으나, 장치 목록을 별도 패널에 시각화하는 기능은 아직 없다.
- 채널별 상세 파라미터는 설정 파일에서 관리되며, GUI에서 편집 가능한 항목은 아직 제한적이다.
- 16채널 확장 전제는 코드 구조상 열려 있으나, 현재 기본 예제와 테스트는 8채널 중심이다.
- 자동화 UI는 `main_window.py` 안에 통합되어 있으며, 전용 패널 모듈 분리는 아직 진행 전이다.
- 자동화 안전 계층은 기본 중단/타임아웃과 모션 설정 소프트 리밋 수준이다. 사용자 확인형 인터락과 복구 절차 표준화는 아직 없다.

### 3.3 미구현 또는 후순위

- 클라우드 업로드
- 데이터베이스 저장
- 자동 리포트 생성
- 고급 분석 기능
- 장비 상태 대시보드
- 알람 및 임계값 관리

## 4. 현재 UI 동작 기준

메인 화면은 세 영역으로 구성된다.

- 상단 운영 바: 상태, 백엔드, 활성 채널 수, export 경로 요약, 연결/시작/일시정지/재개/정지 버튼
- 좌측 스택: 세션 설정 패널, 로그 패널
- 우측 스택: 모듈 카드 영역, 그래프 영역

세션 패널에서 현재 직접 조작 가능한 항목은 다음과 같다.

- 백엔드 선택(`simulation`, `ni`)
- 세션 라벨(`Session Label`)
- CSV 저장 폴더 선택
- 취득 주기(`Acquisition Hz`)
- 표시 주기(`Display Hz`)
- 모듈/포트별 활성화 토글
- 자동화 레시피 로드(`Load Recipe`)
- 자동화 레시피 생성 헬퍼(`Recipe Helper`)
- 모션 설정 로드(`Load Motion`)
- 자동화 실행/중단(`Run Automation`, `Stop Automation`)
- 자동화 상태와 현재 step 표시
- AO 없는 자동화 전용 프로필과 실행 진입점

파일 메뉴에서 다음 작업을 수행할 수 있다.

- `Load Config`
- `Save Config`
- `Quit`

## 5. 측정 처리 방식

### 5.1 백엔드 구조

- `SimulatedBackend`: 사인파, drift, noise를 조합해 가상의 저항 변화를 생성한다.
- `NiDaqBackend`: 활성 채널만 `nidaqmx.Task()`에 등록하고 연속 취득 모드로 읽는다.
- `AcquisitionController`: UI 스레드와 분리된 백그라운드 스레드에서 취득을 수행하고, queue로 샘플을 전달한다.

### 5.2 NI 9234 대응 방식

`NI 9234`는 저속 정적 신호 장비가 아니므로 최소 샘플링 속도 제약을 고려해야 한다. 현재 구현은 다음 원칙을 사용한다.

- 목표 취득 주기보다 낮더라도 실제 하드웨어 읽기 속도는 최소 `1652 Hz`
- 한 번 읽을 때 여러 샘플을 받아 채널별 평균값 계산
- 평균된 전압값을 저항값으로 환산 후 UI와 CSV에 사용

즉, 현재 문서 기준으로 저장되는 값은 원시 고속 샘플 전체가 아니라 표시 주기에 맞춰 평균 처리된 값이다.

## 6. 계산 로직 기준

현재 계산 로직은 채널별 `bridge_type`을 기준으로 동작한다.

- `quarter_bridge`
- `half_bridge`
- `full_bridge`
- 그 외 값은 일반 fallback 식 사용

채널 설정 필드는 다음을 사용한다.

- `enabled`
- `name`
- `physical_channel`
- `bridge_type`
- `excitation_voltage`
- `nominal_resistance_ohm`
- `zero_offset`
- `calibration_scale`
- `color`

현재 상태 판정은 `nominal_resistance_ohm + zero_offset` 대비 편차를 기준으로 한다.

- 편차 `> 4.5`: `error`
- 편차 `> 3.0`: `warning`
- 그 외: `normal`

## 7. 설정 파일 기준

기본 설정 파일은 `config/channel_settings.example.json`이다.

현재 예제 설정의 기본값은 다음과 같다.

- 백엔드: `simulation`
- 기본 export 경로: `dev_local/exports`
- 취득/표시 주기: `10 Hz / 10 Hz`
- 히스토리 길이: `300초`
- 기본 채널 수: `8`
- 기본 브리지 타입: `quarter_bridge`
- 기본 기준 저항: `350 ohm`
- 기본 인가 전압: `5.0 V`

## 8. 저장소 및 테스트 운영 기준

- 배포 필수 코드와 공용 문서는 저장소 루트에 둔다.
- 테스트 코드와 실험 산출물은 모두 `dev_local/` 아래로 분리한다.
- `pytest` 기본 경로는 `dev_local/tests`
- `pytest` cache provider는 비활성화해 테스트 잔여물이 루트에 다시 생기지 않도록 유지한다.

현재 확인된 자동 테스트 범위는 주로 채널 매핑/정규화 관련 테스트다. GUI, CSV 저장, NI 실제 하드웨어 경로는 수동 검증 비중이 높다.

현재 자동 테스트에는 자동화 레시피 로드, 자동화 러너, 자동화 패널, 세션 저장 경로, SHOT 계열 모션 어댑터 단위 테스트가 포함된다. NI 실장비 연동은 아직 수동 검증 비중이 높다. 실제 `SHOT-102` 직렬 통신은 2026-04-20 기준 `COM10`에서 status 조회, 상대 이동, 방향키 jog, origin 복귀까지 수동 검증을 완료했다.

## 9. 현재 구현 기준 아키텍처

- `src/p_sensor/app.py`
  애플리케이션 시작점, 기본 설정 로드, 메인 윈도우 실행
- `src/p_sensor/config.py`
  기본 설정 생성, JSON 로드/저장, 채널명 및 물리 채널 정규화
- `src/p_sensor/models.py`
  설정, 샘플, 읽기 데이터 모델 정의
- `src/p_sensor/calculations.py`
  전압-저항 환산 및 상태 판정
- `src/p_sensor/storage.py`
  CSV recorder와 세션 식별자/세션 경로 helper
- `src/p_sensor/acquisition/base.py`
  백엔드 추상화와 취득 컨트롤러
- `src/p_sensor/acquisition/simulated.py`
  시뮬레이션 백엔드
- `src/p_sensor/acquisition/ni.py`
  NI-DAQmx 백엔드
- `src/p_sensor/services/measurement.py`
  공용 측정 엔진 래퍼와 측정 창 집계
- `src/p_sensor/automation/models.py`
  자동화 레시피, step, 세션 결과 모델
- `src/p_sensor/automation/recipe.py`
  자동화 레시피 JSON 로드
- `src/p_sensor/automation/runner.py`
  자동화 오케스트레이션과 step 실행 상태 관리
- `src/p_sensor/automation/safety.py`
  자동화 목표 변위와 실제 모션 위치 소프트 리밋 검증
- `src/p_sensor/automation/smoke_cli.py`
  시뮬레이션 DAQ와 선택적 SHOT 계열 모션을 사용한 자동화 smoke 실행기
- `src/p_sensor/automation/storage.py`
  자동화 세션 폴더, manifest, summary, 측정 CSV 저장
- `src/p_sensor/motion/shot102.py`
  SHOT 계열 직렬 제어와 `OSMS20-35`/`SGSP20-85` 기준 명령 브리지
- `src/p_sensor/motion/shot102_cli.py`
  `SHOT-702`/`SHOT-102` 실장비 status, jog, origin 점검용 CLI
- `src/p_sensor/ui/main_window.py`
  메인 GUI, 수동 측정, 자동화 패널, 로그, 설정 적용

## 10. 향후 자동화 확장 계획

리니어 스테이지를 이용해 변위 단계별로 센서를 누르면서 DAQ에서 저항값을 읽고 매칭하는 자동화 기능을 향후 확장 범위로 둔다. 이때 중요한 원칙은 자동화 기능이 기존 DAQ 측정 루프를 흡수하지 않고, 재사용 가능한 공용 측정 엔진 위에 상위 오케스트레이션 계층으로 올라가야 한다는 점이다.

현재 방향은 다음과 같다.

1. `acquisition` 계층은 단일 DAQ 측정 루프로 유지하고 다른 프로젝트에서도 재사용 가능하게 둔다.
2. 리니어 스테이지 제어는 별도 `motion` 계층으로 분리한다.
3. 변위 step 실행, 안정화 대기, 측정 집계, 결과 저장은 `automation` 계층에서 담당한다.
4. UI는 수동 측정 패널과 자동화 패널을 조합하는 구조로 점진 분리한다.
5. 세션 식별자, 세션별 폴더, 측정 창별 CSV 저장 구조를 자동화 기본 정책으로 둔다.
6. 장비 어댑터는 SHOT 계열을 기준으로 구현하되, 상위 오케스트레이션은 장비 독립 인터페이스를 유지한다.
7. 검증된 SHOT 계열 모션 모듈은 오케스트레이션에서 직접 직렬 명령을 노출하지 않고 명령 브리지 뒤에 둔다.
8. 다음 개발 단계는 `move -> ready wait -> settle -> measurement window -> result save -> disengage/origin` 순서를 안전하게 실행하는 오케스트레이션 계층 정리다.

자세한 계획은 `docs/linear_stage_automation_plan_ko.md`를 기준 문서로 사용한다.

현재 자동화 하드웨어 전제는 다음과 같다.

- 스테이지는 `OPTOSIGMA OSMS20-35`
- 컨트롤러는 `OPTOSIGMA SHOT-702`
- 호스트 제어는 `RS-232C` 기반
- 자동화 코드는 SHOT 계열 호스트 제어 명령 체계를 기준으로 구현

## 11. 남은 과제

우선순위가 높은 후속 작업은 다음과 같다.

1. 사용자 확인형 인터락과 오류 복구 절차 표준화
2. `move -> settle -> measure -> disengage/origin` 실행 흐름의 수동 하드웨어 체크리스트 문서화
3. 실제 NI DAQ backend와 `Shot102CommandBridge`를 조합한 전체 자동화 흐름 검증
4. `main_window.py`에 집중된 자동화 UI를 패널 단위 모듈로 분리
5. CSV 저장과 설정 직렬화에 대한 자동 테스트 확대
6. NI 장비와 슬롯 정보를 화면에 표시하는 연결 진단 UI 추가
7. 채널 상세 파라미터 편집 UI 추가
8. 16채널 구성에서의 레이아웃 및 성능 검증

## 12. 실행 및 검증 명령

```powershell
.\scripts\setup_env.ps1
.\scripts\run_app.ps1
.\scripts\run_automation_smoke.ps1 --session-label shot702_smoke_real
.\.venv\Scripts\python.exe -m pytest
```

## 13. 참고 문서

- 저장소 정책: `docs/repository_policy_ko.md`
- 자동화 계획: `docs/linear_stage_automation_plan_ko.md`
- 협업 절차: `docs/github_vscode_cheatsheet_ko.md`
- 기본 설정 예제: `config/channel_settings.example.json`
