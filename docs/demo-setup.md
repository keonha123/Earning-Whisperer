# 데스크탑 앱 실행 방법

백엔드는 제 노트북에서 돌리고 Cloudflare 터널로 외부에 열어둡니다.
그래서 각자 설치할 건 앱 하나뿐입니다. DB나 Redis, 백엔드는 안 깔아도 됩니다.

## 1. 받아오기

Node 20 이상이 필요합니다. `node -v` 로 먼저 확인해 주세요.

```bash
git clone <저장소 주소>
cd Earning-Whisperer/trading-terminal
git checkout keonha/feat/earnings-demo-ui
npm install
```

`npm install` 은 Electron 바이너리를 내려받느라 2~3분쯤 걸립니다.

한 가지 주의할 게, WSL 터미널과 Windows 터미널을 섞어 쓰면
`@rollup/rollup-linux-x64-gnu` 같은 네이티브 모듈이 깨집니다.
clone부터 실행까지 같은 환경에서 하시고, 이미 깨졌다면
`node_modules` 를 지우고 다시 설치하면 됩니다.

## 2. 환경변수

`trading-terminal/.env.local` 파일을 새로 만들어 주세요.
gitignore에 걸려 있어서 clone해도 안 따라옵니다.

```
OAUTH_GOOGLE_CLIENT_ID=804303266932-o1e3m7bv4lvmj41tuapkd083ubf33u3j.apps.googleusercontent.com
OAUTH_KAKAO_CLIENT_ID=6483bd66d222dc21041cb8cb7d2865f7
BACKEND_URL=https://pontiac-starting-maternity-bell.trycloudflare.com
```

`BACKEND_URL` 은 시연 당일에 바뀝니다. 터널을 다시 띄울 때마다 주소가 새로 발급되기 때문입니다.
당일 아침에 제가 최신 주소를 공유드릴 테니 저 줄만 바꾸고 앱을 다시 켜시면 됩니다.

## 3. 실행

```bash
npm run dev
```

Electron 창이 뜨면 된 겁니다.

`npm run build` 로 만든 패키지 버전은 쓰지 말아 주세요.
시연용 화면들이 개발 모드에서만 나오도록 되어 있어서, 빌드본에서는 안 보입니다.

## 4. 로그인

앱에서 구글이나 카카오로 로그인하시면 기본 브라우저가 열렸다가 앱으로 돌아옵니다.
콜백을 9000 포트로 받으니, 그 포트를 쓰는 다른 프로그램이 떠 있으면 미리 꺼주세요.

## 안 될 때

먼저 백엔드가 살아있는지부터 봅니다.
브라우저에서 `BACKEND_URL` 뒤에 `/actuator/health` 를 붙여 열었을 때
`{"status":"UP"}` 이 나오면 서버 쪽은 정상입니다.

- 창은 뜨는데 데이터가 안 들어오면 `BACKEND_URL` 이 옛날 주소일 가능성이 큽니다.
- 로그인 후 앱으로 안 돌아오면 9000 포트가 막힌 겁니다.
- 모듈을 못 찾는다는 에러가 나면 위에 적은 WSL/Windows 혼용 문제입니다.
- 셋 다 아니면 백엔드가 꺼진 거니 저한테 연락 주세요.

참고로 공유기나 모바일 핫스팟에 따라 방금 만들어진 `trycloudflare.com` 주소를
못 찾는 경우가 있습니다. 저도 겪었는데, PC의 DNS를 1.1.1.1로 바꾸니 해결됐습니다.
