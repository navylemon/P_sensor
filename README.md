# P_sensor

`NI cDAQ-9174 + NI 9234 + NI 9265` 조합용 데스크톱 측정/출력 GUI다.

현재 프로그램은 기본적으로 다음 구성을 사용한다.

- AI 2채널: `NI 9234`
- AO 2채널: `NI 9265`
- 백엔드: `simulation`, `ni`
- 저장 형식: 세션별 폴더 + CSV

기존 루트 프로그램은 `P_sensor_v0.2_archive_20260414/`에 아카이브했다.

## 현재 기능

- `simulation` 백엔드로 GUI와 저장 흐름을 먼저 검증 가능
- `ni` 백엔드에서 `9234` 입력과 `9265` 출력 동시 사용
- `9234` 입력값을 표시 주기에 맞게 평균화해서 표시
- `9265` 출력 전류를 채널별 setpoint로 적용
- 입력 추세 그래프 표시
- 수동 측정 시 세션 라벨 입력과 세션별 `measurement.csv` 저장
- 자동화 레시피 로드와 `Run Automation`/`Stop Automation` 실행
- `SIGMAKOKI SGSP20-85` + `SIGMAKOKI SHOT-102` 기준 모션 설정 로드
- 자동화 세션별 `session_manifest.json`, `step_summary.csv`, `measurement_XXXX.csv` 저장
- JSON 설정 파일 저장/불러오기

## 실행

```powershell
.\scripts\setup_env.ps1
.\scripts\run_app.ps1
```

직접 실행:

```powershell
.\.venv\Scripts\python.exe -m p_sensor --profile io
.\.venv\Scripts\python.exe -m p_sensor --profile ai
```

패키지 진입점은 다음으로 정리한다.

- `python -m p_sensor --profile io`
- `python -m p_sensor --profile ai`
- `p-sensor`
- `p-sensor-io`
- `p-sensor-ai`

## 기본 설정 파일

- `config/channel_settings.example.json`
- `config/experiment_recipe.example.json`
- `config/shot102_sgsp20_85.example.json`

기본 예시는 아래를 전제로 한다.

- `cDAQ1`
- `NI 9234` at slot 1
- `NI 9265` at slot 2
- AI: `ai0`, `ai1`
- AO: `ao0`, `ao1`

## 주의

- `ni` 백엔드를 쓰려면 `nidaqmx`와 NI 드라이버가 설치되어 있어야 한다.
- `SHOT-102`를 쓰려면 `pyserial`과 올바른 `RS-232C` 설정이 필요하다.
- `NI 9234`는 저속 단발 샘플링 장비가 아니라 내부적으로 최소 샘플링 속도 제한을 고려한다.
- `NI 9265` 출력은 mA 기준으로 다룬다.
- 실제 장비별 `COM` 포트, `pulses_per_mm`, 홈 방향 같은 값은 `dev_local/config/`에서 관리하는 편이 적절하다.
