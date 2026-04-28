# 실장비 연결 후 안전 검증 자동화 시나리오

이 문서는 실제 `OPTOSIGMA SHOT-702 / OSMS20-35` 스테이지와 NI DAQ를 연결했을 때 프로그램이 목적에 맞게 동작하는지 확인하기 위한 단계형 commissioning 시나리오다. 기본 원칙은 한 번에 모든 장비를 움직이지 않고, DAQ, Stage, Automation 경로를 분리해 검증한 뒤 마지막에만 통합 smoke를 실행하는 것이다.

## 1. 절대 조건

- 작업자는 비상 정지, SHOT-702 전원 차단, 프로그램 Stop 위치를 손이 닿는 곳에 둔다.
- probe와 sample은 처음부터 접촉시키지 않는다. 첫 자동화 검증은 반드시 공중 또는 충분한 clearance 상태에서 수행한다.
- 최초 검증에서는 contact detection과 contact calibration을 사용하지 않는다.
- 최초 검증에서는 `--home-on-connect`, `--origin`, `--calibrate-nominal`을 사용하지 않는다. 원점 복귀는 이동 방향과 충돌 여유가 확인된 뒤 별도 절차로 수행한다.
- 실제 장비 구동 명령에는 항상 로컬 장비 설정을 명시한다. 예: `dev_local\config\shot702_osms20_35.local.json`
- 로컬 motion config의 기본 `port`, `axis`, `min_position_mm`, `max_position_mm`, `pulses_per_mm`, `home_on_connect` 값을 실행 전 눈으로 확인한다. USB-serial 연결 순서에 따라 `COM` 번호가 바뀌면 메인 UI의 Stage `Port` 선택 또는 CLI의 `--port COMx` override를 사용한다. 첫 검증 권장값은 `home_on_connect=false` 또는 CLI에서 home-on-connect를 허용하지 않는 경로다.
- NI DAQ는 `COM` 포트가 아니라 NI-DAQmx 장치명(`cDAQ1`, `Dev1` 등)을 사용한다. USB 재연결 후 장치명이 바뀌었으면 메인 UI의 DAQ `Devices` 새로고침 후 `DAQ Device`에서 현재 장치를 선택한다.
- Stage soft limit은 물리 stroke보다 좁게 설정한다. 첫 이동 검증은 현재 위치와 목표 위치가 모두 soft limit 내부일 때만 진행한다.

## 2. 사용 파일

- Stage 로컬 설정: `dev_local\config\shot702_osms20_35.local.json`
- NI DAQ 로컬 설정: `dev_local\config\verified_ni_runtime.json`
- 안전 commissioning recipe: `config\experiment_recipe_hardware_commissioning.example.json`
- Stage 점검 스크립트: `scripts\check_stage.ps1`
- 자동화 smoke 스크립트: `scripts\run_automation_smoke.ps1`

`config\experiment_recipe_hardware_commissioning.example.json`은 contact detection을 끄고, Stage 1 기준 `0.05 mm -> 짧은 측정 -> 0.0 mm 복귀`만 수행한다.

PowerShell 실행 정책 때문에 `.ps1` 실행이 차단되면 같은 명령을 `.\.venv\Scripts\python.exe -m p_sensor.motion.shot_cli ...` 또는 `.\.venv\Scripts\python.exe -m p_sensor.automation.smoke_cli ...` 형태로 직접 실행한다. 이때도 실장비 구동에는 `--motion-config dev_local\config\shot702_osms20_35.local.json`을 명시해야 한다.

## 3. 단계별 시나리오

### S0. 실행 전 육안 점검

목적: 소프트웨어 실행 전 물리 위험을 제거한다.

1. 스테이지 이동 방향을 확인한다. Stage 1은 Z축, Stage 2는 X축이다.
2. probe가 sample, jig, cable, stopper와 닿지 않는 위치에 있는지 확인한다.
3. SHOT-702와 DAQ의 케이블이 고정되어 있고 이동 중 걸리지 않는지 확인한다.
4. 로컬 motion config 또는 Stage UI `Port` 선택이 실제 COM port와 일치하는지 확인한다.
5. 첫 실행에서는 motion config의 자동 home을 끄거나, 아래 CLI처럼 home-on-connect를 허용하지 않는 경로만 사용한다.

합격 기준: 장비가 움직여도 충돌할 물체가 없고, 정지 수단을 즉시 사용할 수 있다.

중단 기준: 이동 방향을 확신하지 못하거나, probe clearance가 부족하거나, COM port가 불명확하다.

### S1. DAQ 단독 smoke

목적: Stage를 움직이지 않고 NI DAQ 취득과 session 저장 경로만 확인한다.

```powershell
.\scripts\run_automation_smoke.ps1 `
  -Config dev_local\config\verified_ni_runtime.json `
  -Recipe config\experiment_recipe_hardware_commissioning.example.json `
  --no-motion --allow-ni --require-ni `
  --session-label ni_only_commissioning
```

합격 기준:
- `session_id`, `session_dir`, `summary_path`가 출력된다.
- 생성된 measurement CSV에 NI 입력 채널 값이 기록된다.
- Stage가 움직이지 않는다.

중단 기준:
- NI backend 연결 실패, 채널명 불일치, CSV 생성 실패, 비정상적인 값 포화가 나타난다.

### S2. Stage 통신 상태 확인

목적: 스테이지를 움직이지 않고 SHOT-702 연결과 status 응답만 확인한다.

```powershell
.\scripts\check_stage.ps1 `
  -Config dev_local\config\shot702_osms20_35.local.json `
  --axis 1 --status
```

합격 기준:
- `ready_ack=R` 또는 정상 ready 상태가 출력된다.
- 선택 축 위치가 숫자로 출력된다.
- 실행 중 stage가 움직이지 않는다.

중단 기준:
- COM port open 실패, timeout, ready 상태 불명확, 현재 위치가 예상 범위 밖이다.

### S3. Stage 미소 왕복 이동

목적: 축 방향과 pulses/mm 변환이 맞는지 최소 이동으로 확인한다.

먼저 `+0.02 mm` 이동:

```powershell
.\scripts\check_stage.ps1 `
  -Config dev_local\config\shot702_osms20_35.local.json `
  --axis 1 --hold --move-relative-mm 0.02 --wait --status
```

육안으로 안전한 방향인지 확인한 뒤 `-0.02 mm` 복귀:

```powershell
.\scripts\check_stage.ps1 `
  -Config dev_local\config\shot702_osms20_35.local.json `
  --axis 1 --hold --move-relative-mm -0.02 --wait --status
```

합격 기준:
- 이동량이 매우 작고, 기대한 방향으로만 움직인다.
- 복귀 후 위치가 시작 위치 근처로 돌아온다.
- 이상 소음, 케이블 당김, limit 근접이 없다.

중단 기준:
- 방향이 반대이거나, 이동량이 예상보다 크거나, ready 복귀가 지연된다.

### S4. 실제 Stage + simulated DAQ 자동화 smoke

목적: NI DAQ를 제외하고 automation runner와 실제 motion bridge만 통합 확인한다.

```powershell
.\scripts\run_automation_smoke.ps1 `
  -Config config\channel_settings_automation.example.json `
  -Recipe config\experiment_recipe_hardware_commissioning.example.json `
  -MotionConfig dev_local\config\shot702_osms20_35.local.json `
  --require-motion `
  --session-label stage_real_sim_daq_commissioning
```

합격 기준:
- Stage가 `0.05 mm` 위치로 이동한 뒤 `0.0 mm`로 복귀한다.
- 출력 step 요약의 `target`, `engaged`, `disengaged` 값이 의도와 맞는다.
- session manifest가 생성되고 status가 completed다.

중단 기준:
- 자동화가 시작 직후 home 또는 큰 이동을 시도한다.
- `engaged` 또는 `disengaged` 값이 recipe와 맞지 않는다.
- Stage가 ready 상태로 돌아오지 않는다.

### S5. 실제 Stage + NI DAQ 통합 smoke

목적: 실제 DAQ 취득, 실제 Stage 이동, 자동화 session 저장이 하나의 runner 경로에서 모두 동작하는지 확인한다.

```powershell
.\scripts\run_automation_smoke.ps1 `
  -Config dev_local\config\verified_ni_runtime.json `
  -Recipe config\experiment_recipe_hardware_commissioning.example.json `
  -MotionConfig dev_local\config\shot702_osms20_35.local.json `
  --allow-ni --require-ni --require-motion `
  --session-label ni_stage_integrated_commissioning
```

합격 기준:
- Stage 이동은 S4와 동일하게 `0.05 mm -> 0.0 mm` 범위 안에서 끝난다.
- NI measurement CSV가 생성되고 frame 수가 recipe의 `measure_frame_count`와 일치한다.
- summary와 manifest에 recipe path, motion config path, step result가 기록된다.
- 자동화 종료 후 수동 Stage status 조회가 정상이다.

중단 기준:
- DAQ 취득 중 Stage가 멈추지 않거나, CSV가 비어 있거나, session manifest status가 failed/cancelled다.

### S6. GUI 확인

목적: CLI smoke 후 메인 GUI가 같은 장비 상태를 안전하게 보여주고 수동 조작을 막지 않는지 확인한다.

1. 메인 앱 실행.
2. DAQ backend를 `ni`로 선택하되 바로 Record를 누르지 않는다.
3. Stage backend를 `SHOT-702`로 선택하기 전에 motion config의 `home_on_connect` 위험을 다시 확인한다.
4. Stage 연결 후 status와 position dashboard가 갱신되는지 확인한다.
5. `Soft limit`을 현재 위치 기준 좁은 범위로 설정하고, `Min < Max` 상태인지 확인한다.
6. `Live Monitor`만 먼저 실행해 값이 갱신되는지 확인한다.
7. `Record`는 5초 이하로 짧게 실행한 뒤 CSV 저장을 확인한다.

합격 기준:
- 오른쪽 영역은 Recipe Steps와 System Log만 유지된다.
- Stage plot에 위치 갱신이 표시되고, DAQ plot은 실시간 값이 표시된다.
- automation 실행 중 manual DAQ/Stage 조작이 잠긴다.

## 4. 첫 검증에서 하지 않는 항목

- contact calibration 자동 실행
- contact detection이 켜진 recipe 실행
- sample 접촉 상태에서 자동화 실행
- Stage 2/X축 자동화
- `+1 mm` 이상 이동
- 자동 home, origin-zero, goto-origin
- AO 출력 포함 smoke. AO는 NI 입력과 Stage 통합이 안정화된 뒤 별도 low-current 시나리오로 분리한다.

## 5. 결과 기록

각 단계마다 다음을 기록한다.

- 실행 일시
- 사용한 config와 recipe 경로
- session_id와 session_dir
- 시작 전 위치, engage 위치, disengage 위치
- DAQ CSV frame 수와 값 범위
- 비정상 소음, timeout, ready 지연, cable 간섭 여부
- 중단했으면 중단 단계와 원인

S1부터 S5까지 모두 통과한 경우에만 실제 sample 접촉을 포함한 contact calibration 검증으로 넘어간다.
