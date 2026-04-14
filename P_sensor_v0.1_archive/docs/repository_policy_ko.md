# 저장소 구성 원칙

이 프로젝트는 배포에 필요한 실행 코드와 공용 문서만 저장소 루트에 두고, 테스트와 실험 중 생성되는 자산은 `dev_local/` 아래로 격리한다.

## 1. Git에 포함하는 영역

- `src/`
- `scripts/`
- `config/`
- `docs/`
- `README.md`
- `requirements.txt`
- `pyproject.toml`
- `.vscode/`
- 기타 공용 설정 파일

## 2. Git에 포함하지 않는 영역

다음 항목은 로컬 전용 자산으로 취급하며 Git 추적에서 제외한다.

- 테스트 코드와 테스트 중 생성되는 캐시
- 실험용 예제와 프로토타입
- 측정 CSV와 임시 분석 결과
- 개인 메모
- 장비별 개인 설정
- 설치와 부트스트랩 임시 파일

## 3. 로컬 전용 작업 영역

로컬 전용 자산은 모두 `dev_local/` 아래에 둔다.

- `dev_local/tests/`
- `dev_local/examples/`
- `dev_local/exports/`
- `dev_local/tmp/`
- `dev_local/scratch/`
- `dev_local/config/`

`dev_local/` 전체와 `pytest-cache-files-*` 같은 테스트 잔여물은 `.gitignore`에서 제외한다.

## 4. 권장 운영 방식

- 실행 기능은 `src/`와 `scripts/`에서만 관리한다.
- 공용 설정 샘플은 `config/`에 둔다.
- 실제 측정 결과 기본 저장 경로는 `dev_local/exports/`로 유지한다.
- 테스트 파일은 `dev_local/tests/`에 두고 `pyproject.toml`의 `pytest` 설정과 일치시킨다.
- 장비별 또는 사용자별 설정은 `dev_local/config/`에 둔다.

## 5. 작업 규칙

- 루트에 새 폴더를 추가할 때는 배포 필수 영역인지 먼저 판단한다.
- 배포와 무관한 산출물은 루트에 두지 않는다.
- 테스트 실행 후 생기는 캐시와 임시 폴더는 `dev_local/` 또는 ignore 패턴으로 정리한다.
- 공용 저장소에 올릴 필요가 없는 파일은 즉시 로컬 전용 영역으로 이동한다.
