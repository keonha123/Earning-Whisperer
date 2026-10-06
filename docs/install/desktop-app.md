# 데스크톱 앱 설치

EarningWhisperer Terminal 을 Windows PC 에 설치하고, 업데이트하고, 제거하는 방법을 설명합니다.
설치 전 조건은 [요구사항](requirements.md)을 참고합니다.

## 지원 플랫폼

| 플랫폼 | 상태 |
|---|---|
| Windows x64 | `v0.1.0-rc1` 설치 파일 배포 중 |
| macOS | 배포 중인 설치 파일이 없습니다 |

`v0.1.0-rc1` 은 검증 중인 사전 릴리스(pre-release)입니다. 릴리스 노트에 따르면 Windows 에서 설치 후 로그인,
KIS 자격증명 저장, 시연 화면 표시를 확인하는 작업이 남아 있습니다(#115).

## 설치 파일 받기

GitHub 저장소의 Releases 에서 `v0.1.0-rc1` 을 열고 `EarningWhisperer.Terminal.Setup.0.1.0.exe` 를 내려받습니다.

| 항목 | 값 |
|---|---|
| 파일 | `EarningWhisperer.Terminal.Setup.0.1.0.exe` |
| 대상 | Windows x64 |
| 서버 | `https://api.logothea.com` (설치 파일에 포함) |
| sha256 | `32590e94051be9ce04d653eae0dce8adb181108e489e5fc7e4e9d8d65aa1764c` |

내려받은 파일이 릴리스와 같은지 확인하려면 PowerShell 에서 해시를 계산해 위 값과 비교합니다.

```powershell
Get-FileHash .\EarningWhisperer.Terminal.Setup.0.1.0.exe -Algorithm SHA256
```

## 설치

1. 내려받은 `.exe` 를 실행합니다.
2. 코드 서명이 없어 "Windows의 PC 보호" SmartScreen 경고가 나옵니다. `추가 정보` 를 누른 뒤 `실행` 을 누릅니다.
3. 설치 마법사에서 설치 범위(현재 사용자 또는 모든 사용자)와 설치 경로를 고른 뒤 설치를 진행합니다.

<!-- 스크린샷: SmartScreen 경고 창에서 추가 정보를 펼친 상태 -->
<!-- 스크린샷: 설치 마법사의 설치 경로 선택 화면 -->

현재 사용자로 설치하면 관리자 권한을 묻지 않고, 모든 사용자로 설치하면 권한 상승을 요구합니다. 앱 이름은 `EarningWhisperer Terminal` 입니다.

## 첫 실행

앱을 실행하면 로그인 화면이 나옵니다. 로그인과 KIS API 키 등록은 [빠른 시작](../overview/quick-start.md)에
순서대로 정리했습니다.

창의 닫기 버튼을 누르면 앱은 종료되지 않고 작업 표시줄 알림 영역(트레이)으로 숨습니다. 트레이 아이콘 메뉴의
`열기` 로 다시 띄우고 `종료` 로 완전히 끕니다.

로그인이 되지 않으면 시연 서버가 꺼져 있을 수 있습니다. 확인 방법은 [FAQ](../overview/faq.md)에 있습니다.

## 업데이트

자동 업데이트 기능은 없습니다. 새 버전이 릴리스되면 같은 방법으로 새 설치 파일을 내려받아 설치합니다.
설치 전에 트레이 메뉴의 `종료` 로 실행 중인 앱을 끕니다.

## 제거

1. 트레이 메뉴의 `종료` 로 앱을 끕니다.
2. Windows 설정의 설치된 앱 목록에서 `EarningWhisperer Terminal` 을 찾아 제거합니다.

KIS API 키와 액세스 토큰은 앱 폴더가 아니라 Windows 자격 증명 저장소에 `EarningWhisperer` 이름으로
저장됩니다. 키까지 지우려면 제거 전에 앱의 `설정` → `KIS Open API 연동` 에서 모의·실전 카드의 `삭제` 를
누릅니다.
