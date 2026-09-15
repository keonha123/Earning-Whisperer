import type { Configuration } from 'electron-builder'

/*
 * 파일명을 `electron-builder.ts` 로 둔다. electron-builder 는 설정 파일을
 * `electron-builder.{yml,yaml,json,json5,toml,js,cjs,mjs,ts}` 이름으로만 찾는다.
 * 이전 이름인 `electron-builder.config.ts` 는 그 목록에 없어 **한 번도 읽히지 않았고**,
 * appId·productName·files·nsis 설정이 전부 무시된 채로 패키징되고 있었다.
 * 산출물이 `EarningWhisperer Terminal` 이 아니라 package.json 의 `name` 으로 나오는 것이
 * 그 증상이었다.
 */

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
  // 네이티브 모듈은 asar 밖으로 뺀다. `.node` 는 dlopen 대상이라 아카이브 안에서 바로
  // 열 수 없고, Electron 이 임시 디렉터리로 복사해 여는 우회에 기대게 된다.
  // keytar 는 KIS 자격증명 저장소라 이게 실패하면 주문 기능 전체가 멈춘다.
  asarUnpack: ['**/*.node'],
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
