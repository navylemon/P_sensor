# P_sensor

`NI cDAQ-9174 + NI 9234 + NI 9265` 기반 센서 측정/자동화 GUI 프로젝트다.

현재 저장소는 수동 측정, AO 출력, 자동화 레시피 실행, `OPTOSIGMA SHOT-702 + OSMS20-35` 리니어 스테이지 연동까지 포함한 `v0.4` 기준 현행 개발 버전을 유지한다. `v0.4`는 실 장비 투입 전 프로그램 개발 완료 단계를 뜻한다. 이전 루트 프로그램은 `P_sensor_v0.2_archive_20260414/`에 보관되어 있다.

## 주요 기능

- `simulation`, `ni` backend 지원
- `NI 9234` 입력과 `NI 9265` 출력 동시 사용
- 실시간 센서 trend, live monitor, CSV 저장
- 자동화 레시피 로드/실행/중단
- `Recipe Helper`, `Protocol` 기반 recipe 생성
- 자동화 진행률, 예상 남은 시간, 예상 종료 시각, phase 표시
- SHOT 계열 stage config 로드, 수동 이동, origin/zero/hold/free/stop
- 자동화 safety 정책, origin 확인, recovery 상태 표시
- 최초 contact detect 실행
  - `Run` 패널에서 on/off와 핵심 파라미터 설정
  - `Safety` 패널에서 설정 상태, scanning 상태, 마지막 검출 결과 표시
  - recipe metadata와 UI 설정 모두 지원
- 자동화 결과 저장
  - `session_manifest.json`
  - `step_summary.csv`
  - `measurement_XXXX.csv`

## 빠른 시작

```powershell
.\scripts\setup_env.ps1
.\scripts\run_app.ps1
```

직접 실행:

```powershell
.\.venv\Scripts\python.exe -m p_sensor --profile io
.\.venv\Scripts\python.exe -m p_sensor --profile ai
.\.venv\Scripts\python.exe -m p_sensor --profile automation
```

엔트리포인트:

- `python -m p_sensor --profile io`
- `python -m p_sensor --profile ai`
- `python -m p_sensor --profile automation`
- `p-sensor`
- `p-sensor-io`
- `p-sensor-ai`
- `p-sensor-automation`
- `p-sensor-stage`
- `p-sensor-shot`

## 자동화 사용 순서

GUI 기준 권장 순서:

1. `.\scripts\run_automation_app.ps1`로 automation 프로파일 GUI를 연다.
2. `Motion`에서 stage config를 확인하거나 로드한다.
3. 실장비 자동화면 `Safety`에서 origin 상태를 확인한다.
4. `Run`에서 recipe를 로드하거나 `Protocol`, `Recipe Helper`로 생성한다.
5. 필요하면 `Run`의 `Contact` 설정을 켠다.
   - axis
   - contact channel
   - scan speed / step / max travel
   - resistance threshold
   - baseline / stable duration
   - `Use0`
6. `Run Auto`를 실행한다.
7. 진행률, ETA, phase, `Safety`의 contact detect 상태를 확인한다.

주의:

- contact detect를 켠 상태에서 motion config가 없으면 `Run Auto`는 비활성화된다.
- 실장비에서는 stage 경로, origin, emergency stop 접근 가능 여부를 먼저 확인해야 한다.

## 자동화 smoke

```powershell
.\scripts\run_automation_smoke.ps1 --no-motion --session-label smoke_dry_run
.\scripts\run_automation_smoke.ps1 --session-label smoke_simulated_motion
.\scripts\run_automation_smoke.ps1 -MotionConfig dev_local\config\stage_shot702_osms20_35.local.json --session-label shot702_smoke_real
```

기본값:

- config: `config/channel_settings_automation.example.json`
- recipe: `config/experiment_recipe_smoke.example.json`
- motion: `config/stage_simulated.example.json`

`config/experiment_recipe_smoke.example.json`에는 contact detect preset 예시가 포함되어 있다.

## stage 점검

```powershell
.\scripts\check_stage.ps1 --status
.\scripts\check_stage.ps1 --jog --jog-step-mm 0.5
.\scripts\check_stage.ps1 --hold-on-connect --origin --origin-zero
```

## 기본 예제 파일

- `config/channel_settings.example.json`
- `config/channel_settings_automation.example.json`
- `config/experiment_recipe.example.json`
- `config/experiment_recipe_smoke.example.json`
- `config/protocol_step_hold.example.json`
- `config/protocol_hysteresis.example.json`
- `config/protocol_speed_dependency.example.json`
- `config/protocol_fatigue.example.json`
- `config/stage_shot702_osms20_35.example.json`
- `config/stage_simulated.example.json`

protocol/experiment recipe 예제에는 `contact_detection` metadata 구조가 포함되어 있다.

## 기본 장비 예시

- `cDAQ1`
- `NI 9234` at slot 1
- `NI 9265` at slot 2
- AI: `ai0`, `ai1`
- AO: `ao0`, `ao1`

## 주의

- `ni` backend를 사용하려면 `nidaqmx`와 NI 드라이버가 설치되어 있어야 한다.
- SHOT 계열 stage 제어를 사용하려면 `pyserial`과 올바른 `RS-232C` 설정이 필요하다.
- `NI 9234`는 저속 정적 신호 전용 장비가 아니므로 내부적으로 최소 샘플링 제약을 고려한다.
- `NI 9265` 출력은 mA 기준으로 다룬다.
- 실제 장비용 `COM` 포트, `pulses_per_mm`, 방향값 등은 `dev_local/config/`에서 관리하는 것을 권장한다.

## 참고 문서

- `docs/project_spec_ko.md`
- `docs/linear_stage_automation_plan_ko.md`
- `docs/scripts_cheatsheet_ko.md`
