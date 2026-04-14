# 저항 기반 센서 측정 GUI 프로그램 명세 및 진행 현황

최종 갱신: 2026-04-06

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

## 3. 현재 구현 범위

### 3.1 구현 완료

- `simulation` 백엔드
- `ni` 백엔드의 연속 취득 연결 로직
- 활성 채널 기준 측정 루프와 백그라운드 취득 스레드
- 전압-저항 환산 로직
- 채널별 상태(`normal`, `warning`, `error`) 판정
- 실시간 모듈 카드 표시
- 저항/전압 듀얼 표시 그래프
- 그래프 범위 선택(`10 s`, `1 min`, `5 min`, `All`)
- 채널별 그래프 표시 On/Off
- CSV 저장
- 설정 JSON 저장/불러오기
- 창 geometry 및 splitter 상태 복원
- 기본 테스트 실행 환경

### 3.2 부분 구현

- NI 장비 사용 가능 여부 확인과 연결 오류 메시지는 구현되어 있으나, 장치 목록을 별도 패널에 시각화하는 기능은 아직 없다.
- 채널별 상세 파라미터는 설정 파일에서 관리되며, GUI에서 편집 가능한 항목은 아직 제한적이다.
- 16채널 확장 전제는 코드 구조상 열려 있으나, 현재 기본 예제와 테스트는 8채널 중심이다.

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
- CSV 저장 폴더 선택
- 취득 주기(`Acquisition Hz`)
- 표시 주기(`Display Hz`)
- 모듈/포트별 활성화 토글

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
  CSV recorder
- `src/p_sensor/acquisition/base.py`
  백엔드 추상화와 취득 컨트롤러
- `src/p_sensor/acquisition/simulated.py`
  시뮬레이션 백엔드
- `src/p_sensor/acquisition/ni.py`
  NI-DAQmx 백엔드
- `src/p_sensor/ui/main_window.py`
  메인 GUI, 플롯, 모듈 카드, 로그, 설정 적용

## 10. 남은 과제

우선순위가 높은 후속 작업은 다음과 같다.

1. 채널 상세 파라미터 편집 UI 추가
2. NI 장비와 슬롯 정보를 화면에 표시하는 연결 진단 UI 추가
3. GUI 수동 검증 절차를 문서화하고 반복 가능한 체크리스트로 정리
4. CSV 저장과 설정 직렬화에 대한 자동 테스트 확대
5. 16채널 구성에서의 레이아웃 및 성능 검증
6. 루트에 남은 과거 `pytest-cache-files-*` 잔여물 정리

## 11. 실행 및 검증 명령

```powershell
.\scripts\setup_env.ps1
.\scripts\run_app.ps1
.\.venv\Scripts\python.exe -m pytest
```

## 12. 참고 문서

- 저장소 정책: `docs/repository_policy_ko.md`
- 협업 절차: `docs/github_vscode_cheatsheet_ko.md`
- 기본 설정 예제: `config/channel_settings.example.json`
