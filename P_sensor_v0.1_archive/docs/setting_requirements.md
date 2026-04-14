# [Specification] Nanomaterial Sensor Measurement System with NI 9234

## 1. 개요 (Project Overview)
본 명세서는 나노소재 기반 저항 변화 센서($70\sim90\Omega$)의 미세 변화($<10\%$)를 NI 9234 DAQ 장비로 정밀 측정하기 위한 시스템 구성 및 소프트웨어 요구사항을 정의함.

---

## 2. 하드웨어 구성 (Hardware Setup)

### 2.1 센서 사양 (Sensor Specs)
* **센서 종류:** 저항 변화형 (Piezoresistive / Nanomaterial-based)
* **기본 저항 ($R_s$):** $70 \Omega \sim 90 \Omega$ (평균 $80 \Omega$)
* **측정 범위:** 저항 변화율 10% 미만 ($\Delta R < 8 \Omega$)

### 2.2 회로 토폴로지 (Circuit Topology)
* **방식:** 휘트스톤 브리지 (Quarter Bridge)
* **고정 저항 ($R_1, R_2, R_3$):** $82 \Omega$ 또는 $100 \Omega$ (정밀도 0.1% 권장)
* **인가 전압 ($V_{ex}$):** DC $1.0V$ (외부 파워서플라이 사용)
    * *주의: 낮은 저항으로 인한 센서 발열(Self-heating) 방지를 위해 1V 내외 권장.*

### 2.3 DAQ 및 연결 (DAQ & Connection)
* **장비:** NI 9234 (24-bit Dynamic Signal Acquisition Module)
* **인터페이스:** BNC Connector
* **배선:** * BNC 내부 핀(Sig+) -> 브리지 출력(+)
    * BNC 외부 쉘(Sig-) -> 브리지 출력(-)
* **접지:** 파워서플라이 (-)와 DAQ 섀시(Chassis) 공통 접지 필수.

---

## 3. 소프트웨어 요구사항 (Software Configuration)

### 3.1 NI-DAQmx 채널 설정
* **Channel Type:** Analog Input - Voltage
* **Terminal Config:** `Pseudodifferential`
* **Input Coupling:** `DC` (★가장 중요: NI 9234의 기본 AC 커플링 해제 필수)
* **IEPE Excitation:** `None` (Disabled)
* **Voltage Range:** $\pm 5V$ (NI 9234 고정 사양)

### 3.2 데이터 수집 및 처리 로직
* **Sampling Rate:** 최소 $1,651.6 S/s$ (장비 지원 최소 속도 근처)
* **Signal Smoothing:** * 나노 센서의 노이즈 억제를 위해 수집된 데이터에 **Moving Average(이동 평균)** 또는 **Low-pass Filter** 적용.
* **물리량 변환 (Resistance Calculation):**
    * 측정된 전압($V_{out}$)을 기반으로 실시간 저항($R_s$) 계산 로직 포함.
    * 공식: $R_s = R_{fixed} \times \frac{1 + 2(V_{out}/V_{ex})}{1 - 2(V_{out}/V_{ex})}$

---

## 4. 코딩 에이전트를 위한 구현 가이드 (Agent Instructions)
1. Python의 `nidaqmx` 라이브러리를 사용하며, `ai_coupling` 속성을 반드시 `Coupling.DC`로 명시할 것.
2. 장치 이름(예: `Mod1/ai0`)은 변수로 처리하여 변경 가능하게 할 것.
3. 실시간 그래프 시각화 시, Y축 범위를 저항($\Omega$) 단위로 변환하여 표시할 것.
4. 측정 시작 전 영점 조절(Offset Calibration) 기능을 포함할 것.