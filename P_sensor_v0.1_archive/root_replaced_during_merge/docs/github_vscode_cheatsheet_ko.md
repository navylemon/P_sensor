# GitHub + VS Code 협업 치트시트

최종 갱신: 2026-04-06

이 문서는 Windows + VS Code 환경에서 이 저장소를 받아 개발하고, 현재 프로젝트 운영 원칙에 맞게 작업하는 최소 절차를 정리한 문서다.

## 1. 준비물

- VS Code
- Git
- Python 3.12 또는 3.13
- GitHub 계정
- 필요 시 NI-DAQmx 드라이버

## 2. 최초 설정

Git 확인:

```powershell
git --version
```

Python 확인:

```powershell
python --version
```

Git 사용자 정보 설정:

```powershell
git config --global user.name "YOUR_NAME"
git config --global user.email "YOUR_EMAIL@example.com"
git config --global init.defaultBranch main
git config --global core.autocrlf true
```

## 3. GitHub 연결

SSH 키 생성:

```powershell
ssh-keygen -t ed25519 -C "YOUR_EMAIL@example.com"
```

공개키 복사:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

GitHub에 SSH 키 등록 후 연결 확인:

```powershell
ssh -T git@github.com
```

## 4. 저장소 받기

새로 clone 하는 경우:

```powershell
git clone git@github.com:OWNER/REPOSITORY.git
cd REPOSITORY
code .
```

`p_sensor.code-workspace`를 직접 열어도 된다.

## 5. 개발 환경 구성

가상환경과 의존성 설치:

```powershell
.\scripts\setup_env.ps1
```

가상환경 활성화:

```powershell
.\.venv\Scripts\Activate.ps1
```

앱 실행:

```powershell
.\scripts\run_app.ps1
```

테스트 실행:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 6. 패키지 관리

패키지 추가:

```powershell
.\scripts\pip_sync.ps1 install PACKAGE_NAME
```

패키지 제거:

```powershell
.\scripts\pip_sync.ps1 uninstall PACKAGE_NAME
```

`pip_sync.ps1`는 `install`, `uninstall` 뒤에 자동으로 `requirements.txt`를 동기화한다.

수동 동기화:

```powershell
.\scripts\freeze_requirements.ps1
```

## 7. 현재 저장소 운영 규칙

- 실행 코드와 공용 문서는 루트에 둔다.
- 테스트, 실험, CSV, 임시 파일은 `dev_local/` 아래에 둔다.
- 기본 테스트 경로는 `dev_local/tests/`다.
- 기본 CSV 저장 경로는 `dev_local/exports/`다.
- 설정 예제는 `config/channel_settings.example.json`을 기준으로 사용한다.

## 8. VS Code 사용 팁

현재 워크스페이스 설정은 다음을 기본 전제로 한다.

- 인터프리터: `${workspaceFolder}\\.venv\\Scripts\\python.exe`
- `pytest` 기본 대상: `dev_local/tests`
- `dev_local/`, `__pycache__`, `pytest-cache-files-*`는 기본적으로 explorer와 검색에서 제외

즉, 테스트나 산출물을 보려면 VS Code의 exclude 설정을 일시적으로 해제하거나 PowerShell에서 직접 확인하는 편이 빠르다.

## 9. 권장 일일 작업 흐름

작업 시작:

```powershell
git status --short
git switch -c feature/my-change
.\scripts\run_app.ps1
```

작업 중 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

커밋 전 확인:

```powershell
git status --short
git diff
```

커밋과 push:

```powershell
git add README.md docs config scripts src .vscode pyproject.toml requirements.txt
git commit -m "Describe change"
git push -u origin feature/my-change
```

## 10. 문제 발생 시 우선 확인

- `.\.venv\Scripts\python.exe --version`
- `.\.venv\Scripts\python.exe -m pip --version`
- `git remote -v`
- `git status --short`
- `config/channel_settings.example.json`의 `backend`
- NI 사용 시 `nidaqmx` 설치 여부와 NI-DAQmx 드라이버 상태

## 11. 자주 쓰는 경로

- 실행 진입점: `src/p_sensor/app.py`
- 메인 UI: `src/p_sensor/ui/main_window.py`
- 기본 설정 예제: `config/channel_settings.example.json`
- 로컬 테스트: `dev_local/tests/`
- 로컬 CSV: `dev_local/exports/`
- 로컬 임시 파일: `dev_local/tmp/`

## 12. 공식 문서

- GitHub 계정 생성: https://docs.github.com/get-started/signing-up-for-github
- Git 설정: https://docs.github.com/en/get-started/quickstart/set-up-git
- SSH 연결 개요: https://docs.github.com/en/authentication/connecting-to-github-with-ssh
- SSH 키 생성: https://docs.github.com/articles/generating-a-new-ssh-key?platform=windows
- SSH 키 등록: https://docs.github.com/articles/adding-a-new-ssh-key-to-your-github-account
- 원격 저장소 연결: https://docs.github.com/github/using-git/adding-a-remote
- Git 설치: https://git-scm.com/download/win
