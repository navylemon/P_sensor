# 리니어 스테이지 연동 자동화 계획

최종 갱신: 2026-04-20

## 1. 문서 목적

이 문서는 `P_sensor`에 리니어 스테이지 제어를 포함한 변위 단계별 저항값 취득 자동화를 정리한 계획 문서다. 현재 기준 하드웨어는 `OPTOSIGMA OSMS20-35`와 `OPTOSIGMA SHOT-702`로 고정하되, 상위 구조는 계속 장비 독립적으로 유지한다.

## 2. 목표 시나리오

자동화가 필요한 대표 시나리오는 다음과 같다.

1. 사용자가 실험 레시피를 선택한다.
2. 프로그램이 DAQ와 리니어 스테이지를 연결한다.
3. 스테이지를 목표 변위로 이동시킨다.
4. 안정화 대기 후 DAQ에서 저항 또는 전압 기반 환산값을 읽는다.
5. 단계별 결과를 저장한다.
6. 다음 변위 단계로 반복한다.

현재 계획 기준으로 핵심 자동화 대상은 `변위 -> 측정 -> 기록` 시퀀스다. 힘 제어가 필요한 경우에도, 초기에 구조를 `변위 기반 스윕 + 선택적 힘 피드백`으로 잡아 두면 장비 확정 전까지 불필요한 가정을 줄일 수 있다.

2026-04-20 기준 `SHOT-102` 모션 모듈은 실장비에서 1차 검증을 완료했다. 따라서 다음 우선 구현 대상은 검증된 모션 명령 브리지를 사용해 위 시나리오를 순서대로 실행하는 `오케스트레이션 계층`이다.

## 3. 현재 전제와 제약

- 기존 프로그램은 DAQ 중심 GUI와 취득 컨트롤러 구조를 이미 갖고 있다.
- 단일 DAQ 측정 루프는 다른 프로젝트에서도 재사용할 가능성이 높다.
- 리니어 스테이지 하드웨어는 `OPTOSIGMA OSMS20-35`, 컨트롤러는 `OPTOSIGMA SHOT-702`를 기준으로 한다.
- 스테이지 제어 통신은 `SHOT-702`의 `RS-232C` 호스트 제어를 기준으로 한다.
- 힘 값이 스테이지 내장 피드백인지, 별도 센서 기반인지도 아직 확정되지 않았다.
- 따라서 지금 단계에서는 "자동화 로직"과 "장비 제어 구현"을 강하게 분리해야 한다.

현재 하드웨어 전제에서 중요한 제약은 다음과 같다.

- `OSMS20-35`는 limit sensor normal close, origin sensor normal open 전제를 기준으로 한다.
- 변위 명령은 실제로는 펄스 단위 명령으로 내려가므로 `mm -> pulse` 환산 설정이 필요하다.
- `SHOT-702`는 `RS-232C`에서 baudrate, delimiter, flow control 설정을 맞춰야 한다.

2026-04-20 수동 검증 결과:

- 연결 포트: `COM10`
- 컨트롤러 ROM: `V1.10`
- 검증 명령: status 조회, 상대 이동, 방향키 jog, origin 복귀
- 오케스트레이션 smoke: `0.5 mm` 절대 이동, 측정 창 수집, `0.0 mm` disengage 복귀 완료
- 점검 진입점: `scripts/check_shot702_stage.ps1`
- smoke 진입점: `scripts/run_automation_smoke.ps1`
- 구현 모듈: `src/p_sensor/motion/shot102.py`, `src/p_sensor/motion/shot102_cli.py`
- 현재 기준 `pulses_per_mm` 기본값은 `1000.0`이며, 컨트롤러 step 설정에 따라 `500.0` 등으로 조정 가능해야 한다.

## 4. 핵심 정책

### 4.1 DAQ 루프 재사용 우선

- 단일 DAQ 측정 루프는 자동화 기능 아래에 종속시키지 않는다.
- DAQ 연결, 취득, 평균화, 스케일링, 프레임 전달은 독립 모듈로 유지한다.
- 자동화 기능은 이 루프를 호출하거나 구독하는 상위 계층으로 둔다.
- 다른 프로젝트가 GUI 없이도 동일한 측정 루프를 사용할 수 있어야 한다.
- 자동화 시퀀스에서 DAQ는 항상 켜져 있는 기본 루프가 아니라, `필요한 측정 구간에만 활성화되는 측정 창(window)`으로 취급한다.

### 4.2 장비 독립 인터페이스 우선

- 스테이지 제조사가 확정되기 전까지 UI나 실험 러너에 제조사 SDK 호출을 직접 넣지 않는다.
- `move_to`, `home`, `stop`, `get_position`, `is_busy` 같은 공통 인터페이스를 먼저 정의한다.
- 벤더별 차이는 어댑터에서만 처리한다.

현재 기준 구현은 SHOT 계열 어댑터를 제공하되, 상위 오케스트레이션은 계속 장비 독립 인터페이스를 사용한다.

### 4.3 실험 시나리오 우선

- 구현 기준은 특정 장비 명령 집합이 아니라 `단계형 실험 레시피`다.
- 레시피는 목표 변위, 대기 시간, 반복 횟수, 측정 샘플 수, 중단 조건 같은 실험 의미를 표현해야 한다.
- 장비 제어 코드는 레시피를 실행하는 수단이어야 하며, 실험 정의를 오염시키지 않아야 한다.

### 4.4 안전 우선

- 스테이지 자동화는 수동 측정보다 위험하므로, 홈 확인, 소프트 리밋, 정지 명령, 타임아웃, 비상 중단 경로를 초기 설계에 포함한다.
- 첫 실장 전에는 시뮬레이션 모드에서 동일한 실행 흐름을 검증할 수 있어야 한다.
- disengage 구간에서는 측정 루프가 불필요하게 계속 동작하지 않도록 기본 동작을 `pause` 또는 `windowed acquisition` 기준으로 설계한다.

### 4.5 데이터 일관성 우선

- 자동화 세션은 단계별 변위, 측정 시각, 안정화 시간, 집계 방식, 장비 식별자, 설정 스냅샷을 함께 저장해야 한다.
- CSV 한 파일만으로 끝내지 말고, 세션 메타데이터와 결과 테이블을 함께 남길 수 있는 구조를 준비한다.
- 사용자가 입력한 세션 식별자 또는 측정 시작 일시를 기준으로 세션을 구분할 수 있어야 한다.
- 세션마다 독립 폴더를 만들고, 단계별 또는 측정 창별 원시/집계 데이터를 별도 CSV로 저장할 수 있어야 한다.

## 5. 목표 아키텍처

향후 구조는 아래 네 계층으로 나누는 것이 적절하다.

### 5.1 Device Layer

- `acquisition/`
  현재 DAQ 측정 백엔드와 취득 컨트롤러를 담당한다.
- `motion/`
  리니어 스테이지 추상 인터페이스와 벤더별 어댑터를 담당한다.
- `sensing/` 또는 `force/`(필요 시)
  별도 힘 센서가 들어올 경우에만 추가한다.

### 5.2 Service Layer

- `measurement service`
  단일 측정 세션 시작, 정지, 프레임 수집, 측정 창 제어, 평균화 정책을 담당한다.
- `scenario/orchestration service`
  단계 실행 순서, engage/disengage 전환, 대기, 측정 요청을 담당한다.
- `motion command bridge`
  아직 스테이지 드라이버가 없더라도 오케스트레이터가 호출할 수 있는 최소 제어 포인트를 제공한다.
- `experiment runner`
  레시피를 읽고 단계별 실행 순서를 오케스트레이션한다.
- `safety/interlock service`
  타임아웃, 범위 초과, 사용자 중단, 장비 오류를 일관되게 처리한다.

### 5.3 Domain Layer

- `experiment recipe`
  변위 시작점, 종료점, step 크기, 안정화 시간, 측정 반복 수
- `measurement point`
  단계별 목표값, 실제 위치, 측정 집계값, 상태
- `session manifest`
  장비 정보, 설정 스냅샷, 실행 시각, 결과 파일 경로

### 5.4 UI Layer

- 메인 창은 조합과 상태 표시 역할만 담당한다.
- 측정 설정, 스테이지 설정, 자동화 레시피, 결과 미리보기는 패널 단위로 분리한다.
- 자동화 레시피는 수동 JSON 편집만 강제하지 않고, 기본적인 변위 스윕을 생성하는 헬퍼를 제공한다.
- 장비 미연결 상태에서도 레시피 편집과 시뮬레이션 검토가 가능해야 한다.

## 6. 권장 모듈 분리 방향

현 구조를 크게 깨지 않으면서 다음 순서로 분리하는 것이 적절하다.

### 6.1 DAQ 측정 루프 분리

현재의 `MeasurementBackend`와 `AcquisitionController`는 재사용 가능한 출발점이다. 앞으로는 이 계층을 "자동화 전용"이 아닌 "공용 측정 엔진"으로 명확히 취급한다.

권장 방향:

- `src/p_sensor/acquisition/`
  DAQ 백엔드와 취득 컨트롤러를 유지
- `src/p_sensor/services/measurement.py`
  GUI나 자동화 러너가 공통으로 사용하는 측정 시작/정지, 측정 창 제어, 집계 인터페이스 추가
- `src/p_sensor/models.py`
  공용 측정 프레임은 유지하되, 자동화용 결과 모델은 별도 네임스페이스로 분리

핵심은 `자동화가 DAQ 루프를 소유하지 않고 활용만 하도록` 경계를 유지하는 것이다.

여기서 중요한 점은 "매 step마다 DAQ를 완전히 재연결할 것인가"와 "연결은 유지하고 측정 루프만 window 단위로 활성화할 것인가"를 분리하는 것이다. 현재 구조상 더 유력한 방향은 다음과 같다.

- 세션 시작 시 DAQ 연결은 1회 수행
- 오케스트레이터가 누르는 구간에서만 `resume` 또는 측정 창 시작
- 측정이 끝나면 `pause`
- 세션 종료 시 연결 해제

이 방식은 하드웨어 재초기화 비용을 줄이면서도 "누를 때만 측정" 요구를 만족시킨다.

### 6.2 리니어 스테이지 계층

스테이지 드라이버는 `SHOT-102` 기준으로 1차 구현과 수동 실장비 검증을 완료했다. 다음 단계에서는 어댑터 존재 자체보다, 상위 오케스트레이션과 안전 계층을 더 분리하는 편이 적절하다.

현재 적용 기준:

- 오케스트레이터는 `engage`, `disengage`, `wait_ready`, `abort` 같은 명령 포인트만 기대한다.
- 다른 스테이지로 교체될 때는 같은 명령 포인트를 유지하면서 어댑터만 교체한다.
- CLI 점검 도구는 수동 검증 전용으로 유지하고, 오케스트레이션 런타임에서는 직접 호출하지 않는다.
- 스테이지 위치 제한은 우선 `Shot102MotionConfig`의 `min_position_mm`, `max_position_mm`, `enforce_software_limits`로 관리한다.

권장 후보 구조:

- `src/p_sensor/motion/base.py`
- `src/p_sensor/motion/simulated.py`
- `src/p_sensor/motion/factory.py`
- `src/p_sensor/motion/<vendor_name>.py`

현재 구현 파일 구조는 다음과 같다.

- `src/p_sensor/motion/shot102.py`
- `src/p_sensor/motion/shot102_cli.py`
- `scripts/check_shot702_stage.ps1`
- `scripts/check_shot102_stage.ps1`
- `config/shot702_osms20_35.example.json`
- `config/shot102_sgsp20_85.example.json`

`base.py`에는 최소한 다음 책임이 필요하다.

- 연결 / 해제
- 홈
- 절대 위치 이동
- 상대 위치 이동
- 정지
- 현재 위치 조회
- busy / ready 상태 조회

### 6.3 자동화 오케스트레이션 추가

권장 후보 구조:

- `src/p_sensor/automation/models.py`
- `src/p_sensor/automation/recipe.py`
- `src/p_sensor/automation/runner.py`
- `src/p_sensor/automation/safety.py`
- `src/p_sensor/automation/results.py`

이 계층은 다음 역할만 맡는다.

- 레시피 해석
- 단계 상태 머신 관리
- engage / settle / measure / disengage 순서 관리
- 단계 실행 순서 제어
- 안정화 대기
- 측정 집계 요청
- 결과 저장 호출
- 중단/재시도 정책

DAQ 세부 동작이나 스테이지 SDK 세부 동작은 이 계층에 넣지 않는다.

### 6.4 UI 패널 분리

현재 `src/p_sensor/ui/main_window.py`는 기능이 많아, 자동화가 추가되면 비대해질 가능성이 높다. 따라서 메인 창은 조합 지점으로 남기고 패널을 점진적으로 나누는 방향이 적절하다.

권장 후보 구조:

- `src/p_sensor/ui/main_window.py`
- `src/p_sensor/ui/session_panel.py`
- `src/p_sensor/ui/ai_panel.py`
- `src/p_sensor/ui/ao_panel.py`
- `src/p_sensor/ui/motion_panel.py`
- `src/p_sensor/ui/automation_panel.py`
- `src/p_sensor/ui/log_panel.py`
- `src/p_sensor/ui/plot_panel.py`

## 7. 자동화 실행 흐름 초안

1. 사용자가 레시피와 장비 설정을 불러온다.
2. 프로그램이 DAQ 측정 엔진을 연결한다.
3. 오케스트레이터가 단계 목록을 순서대로 실행한다.
4. 각 step에서 `engage` 명령을 호출한다.
5. 안정화 시간 동안 대기한다.
6. DAQ 측정 엔진을 `resume` 또는 측정 창 시작 상태로 전환한다.
7. 지정 횟수 또는 지정 시간만큼 데이터를 수집한다.
8. 평균값 또는 대표값을 계산한 뒤 DAQ를 `pause`한다.
9. `disengage` 명령을 호출한다.
10. `변위-저항` 매칭 결과와 세션 메타데이터를 저장한다.
11. 사용자가 중단하거나 마지막 step이 끝날 때까지 반복한다.

이 흐름은 실제 스테이지 드라이버가 검증된 현재 단계에서도 동일하게 유지한다. 차이는 `NoOpCommandBridge` 대신 `Shot102CommandBridge`를 연결해 같은 오케스트레이션 경로를 실장비에서 실행한다는 점이다.

## 8. 오케스트레이션 우선 구현 전략

검증된 리니어 스테이지 모듈을 기준으로 다음 코드를 우선 정리한다.

### 8.1 측정 서비스

- DAQ 연결
- 취득 시작
- 취득 일시정지 / 재개
- 지정 시간 또는 지정 프레임 수 수집
- 대표값 집계

현재 `AcquisitionController`의 `connect`, `start`, `pause`, `resume`, `stop` 흐름을 감싸는 서비스 계층을 두면, GUI와 자동화 러너가 같은 측정 엔진을 공유할 수 있다.

### 8.2 시나리오 러너

- step 목록 실행
- 각 step의 상태 전이 관리
- 대기와 타임아웃 관리
- 중단 처리
- 결과 누적 저장

### 8.3 명령 브리지

- `engage(step)`
- `disengage(step)`
- `abort()`
- `wait_until_ready(timeout_s)`

이 계층은 이미 `Shot102CommandBridge`로 실장비 연결이 가능하다. 오케스트레이션 개발 중에는 동일 인터페이스의 `NoOpCommandBridge` 또는 시뮬레이션 브리지를 사용해 하드웨어 없이 흐름을 검증하고, 실장비 검증 단계에서만 `Shot102CommandBridge`로 교체한다.

### 8.4 다음 개발 체크리스트

오케스트레이션 개발은 다음 순서로 준비한다.

1. 완료: `AutomationStepResult`와 `step_summary.csv`에 `position_before_mm`, `position_after_engage_mm`, `position_after_disengage_mm`를 기록한다.
2. 완료: `automation/safety.py`를 추가해 목표 변위와 실제 모션 위치 소프트 리밋 검증을 분리한다.
3. 다음: 사용자 확인형 인터락, ready timeout 분류, emergency stop 이후 복구 절차를 표준화한다.
4. 완료: 첫 실장비 오케스트레이션은 `0.5 mm` 단일 step smoke recipe로 검증한다.
5. 유지: `ExperimentRunner`는 상태 전이와 저장 호출만 담당하고, 모션 세부 명령과 DAQ 세부 동작은 각각 bridge/service 뒤에 둔다.
6. 다음: 실제 NI DAQ backend와 `Shot102CommandBridge`를 함께 사용하는 장비 통합 smoke를 검증한다.

## 9. 세션 저장 전략

자동화 실험은 반복 측정과 사후 분석이 핵심이므로, 저장 단위를 "앱 전체"가 아니라 "측정 세션" 기준으로 잡는 것이 적절하다.

### 9.1 세션 식별자

- 사용자는 세션 시작 전에 텍스트 식별자를 입력할 수 있어야 한다.
- 사용자가 입력하지 않으면 측정 시작 시각으로 기본 식별자를 생성한다.
- 권장 기본 형식은 `YYYYMMDD_HHMMSS`다.
- 사용자가 입력한 식별자가 있으면 안전한 파일명 규칙으로 정규화한 뒤 시각 접미사를 붙일 수 있다.

예시:

- `20260414_173000`
- `sample_A_20260414_173000`
- `force_sweep_01_20260414_173000`

### 9.2 세션 폴더 구조

세션마다 독립 폴더를 만든다.

권장 예시:

- `dev_local/exports/session_force_sweep_01_20260414_173000/`

세션 폴더에는 최소한 다음 파일을 둔다.

- `session_manifest.json`
  세션 식별자, 시작 시각, 장비/설정 스냅샷, 레시피 정보
- `step_summary.csv`
  step별 목표값, 실제값, 집계값, 상태
- `measurement_0001.csv`
- `measurement_0002.csv`
- `measurement_0003.csv`

여기서 `measurement_XXXX.csv`는 각 측정 창에서 DAQ가 실제로 수집한 데이터를 의미한다.

### 9.3 CSV 저장 원칙

- `step_summary.csv`는 전체 세션의 요약 테이블이다.
- 각 측정 구간에서 수집한 데이터는 별도 CSV 파일로 저장한다.
- 한 step에서 여러 번 측정하면 측정 횟수 기준으로 파일을 분리한다.
- CSV 파일명만으로도 실행 순서를 알 수 있도록 일련번호를 포함한다.
- 세션 종료 후에는 요약 CSV와 원시 CSV가 같은 세션 폴더 아래에 남아야 한다.

### 9.4 측정 파일과 요약 파일의 역할 분리

- 원시/창 단위 CSV
  시간축 데이터, 전압, 환산값, 필요 시 AO 출력값
- 요약 CSV
  step 번호, 목표 변위, settle 시간, 측정 파일명, 대표 저항값, 상태, 비고

이렇게 분리하면 사후 분석과 재현성이 좋아지고, 특정 측정 구간만 다시 확인하기도 쉬워진다.

## 10. 설정 파일 전략

장비 미확정 상태에서는 설정을 세 층으로 나누는 것이 안전하다.

- 공용 앱 설정
  기존 `AppConfig` 계열. UI, DAQ 채널, export 경로 등
- 실험 레시피 설정
  변위 step, 안정화 시간, 샘플 집계 정책 등
- 장비별 로컬 설정
  포트명, COM 설정, 속도 제한, 홈 방향, 소프트 리밋 등

권장 경로:

- `config/experiment_recipe.example.json`
- `config/experiment_recipe_smoke.example.json`
- `dev_local/config/linear_stage.<vendor>.json`

장비별 실제 연결 정보는 공용 샘플 파일보다 `dev_local/config/`에 두는 것이 적절하다.

또한 레시피에는 다음 항목을 우선 넣는 것이 적절하다.

- `step_id`
- `target_displacement`
- `settle_time_s`
- `measure_duration_s` 또는 `measure_frame_count`
- `disengage_after_measure`
- `post_disengage_wait_s`
- `session_label` 또는 실행 시 입력받는 세션 식별자 사용 여부

## 11. 단계별 추진 계획

### 1단계. 문서와 인터페이스 고정

- 자동화 요구사항 문서화
- DAQ 재사용 경계 명시
- 측정 창 기반 오케스트레이션 흐름 고정
- 최소 명령 브리지 초안 정의
- 자동화 결과 모델 정의
- 세션 식별자와 저장 구조 정책 고정

### 2단계. 시뮬레이션 기반 자동화

- 시나리오 러너 구현
- 측정 서비스 구현
- SHOT 계열 명령 브리지와 시뮬레이션/대체 브리지 정리
- 레시피 실행 러너 구현
- 변위 step별 가상 측정 결과 저장
- 세션 폴더, 요약 CSV, 측정 CSV 저장 구현

### 3단계. UI 통합

- 자동화 패널 추가
- 수동 측정 모드와 자동 모드 분기
- 세션 상태, 현재 step, 중단 버튼, 결과 미리보기 추가
- 세션 식별자 입력 필드 추가

### 4단계. 실제 스테이지 어댑터 연결

- `SIGMAKOKI SHOT-102` 실기 연동 검증: 2026-04-20 1차 완료
- `SGSP20-85` 홈, 이동, 위치 피드백 검증: 2026-04-20 1차 완료
- `Shot102CommandBridge` 기반 자동화 smoke 검증: 2026-04-20 1차 완료
- 긴급 정지와 오류 상황별 복구 검증
- 장비 오류 메시지 표준화

### 5단계. 안전성과 재현성 보강

- 소프트 리밋
- 타임아웃
- 긴급 정지
- 수동 검증 체크리스트
- 자동화 세션 재현용 메타데이터 보강

## 12. 초기에 제외할 범위

다음 항목은 리니어 스테이지 모듈 확정 전 1차 구현 범위에서 제외하는 것이 적절하다.

- 제조사별 고급 튜닝 기능
- 폐루프 힘 제어
- 클라우드 업로드
- 데이터베이스 저장
- 자동 리포트 생성
- 복잡한 후처리 분석

## 13. 관련 문서

- `docs/project_spec_ko.md`
- `docs/repository_policy_ko.md`
