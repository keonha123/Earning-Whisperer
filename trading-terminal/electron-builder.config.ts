import type { Configuration } from 'electron-builder'

const config: Configuration = {
  appId: 'com.earningwhisperer.terminal',
  productName: 'EarningWhisperer Terminal',
  directories: {
    buildResources: 'resources',
    output: 'dist',
  },
  // resources/icon.png 을 함께 담는다. 트레이 아이콘을 런타임에 경로로 읽는데
  // (src/main/index.ts 의 createTray), out/ 만 담으면 패키징본에서 그 경로가 없어
  // 트레이가 빈 아이콘으로 뜬다. buildResources 는 빌드 시점에만 쓰이기 때문이다.
  files: ['out/**/*', 'resources/icon.png'],
  // 아이콘 경로를 명시하지 않는다. electron-builder 가 buildResources 의 icon.png 에서
  // 플랫폼별 .ico / .icns 를 만들어 준다. 경로를 박아 두면 그 파일을 직접 만들어
  // 저장소에 넣어야 하고, 원본과 어긋날 때 조용히 낡은 아이콘이 박힌다.
  win: {
    target: ['nsis'],
  },
  mac: {
    target: ['dmg'],
    category: 'public.app-category.finance',
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
  },
}

export default config
