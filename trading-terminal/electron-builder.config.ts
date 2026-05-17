import type { Configuration } from 'electron-builder'

const config: Configuration = {
  appId: 'com.earningwhisperer.terminal',
  productName: 'EarningWhisperer Terminal',
  directories: {
    buildResources: 'resources',
    output: 'dist',
  },
  files: ['out/**/*'],
  win: {
    target: ['nsis'],
    icon: 'resources/icon.ico',
  },
  mac: {
    target: ['dmg'],
    icon: 'resources/icon.icns',
    category: 'public.app-category.finance',
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
  },
}

export default config
