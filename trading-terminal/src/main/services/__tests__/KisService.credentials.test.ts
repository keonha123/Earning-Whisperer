import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// 공유 axios mock — setup.ts 에서 vi.mock('axios') 등록.
import { kisHttpMock } from '../../../test/setup'

import keytar from 'keytar'
import { KisService, maskAccountNo, maskAppKey, migrateLegacyKeysIfNeeded } from '../KisService'
import { mainState } from '../../store/mainState'

const KEYTAR_SERVICE = 'EarningWhisperer'

beforeEach(() => {
  mainState.clear()
  mainState.setPaperTrading(true)
  kisHttpMock.get.mockReset()
  kisHttpMock.post.mockReset()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

/**
 * A2: credential 을 모드별 slot 에 분리 저장.
 * paper / real 환경에서 발급받은 키는 별도 키쌍이며 섞이면 KIS 가 거부한다.
 */
describe('KisService.saveCredentials — 모드별 slot 분리', () => {
  it('paper 모드 저장 → kis-{key}-paper slot 에 기록, real slot 은 비어있음', async () => {
    await KisService.saveCredentials('p-key', 'p-secret', '1111111101', true)

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('p-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('p-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('1111111101')

    // real slot 은 손대지 않아야 함
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBeNull()

    // legacy 단일 slot 도 사용하지 않아야 함
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
  })

  it('real 모드 저장 → kis-{key}-real slot 에 기록, paper slot 보존', async () => {
    // 사전에 paper 키가 등록되어 있다면, real 등록이 이를 건드리면 안 됨
    await KisService.saveCredentials('p-key', 'p-secret', '1111111101', true)
    await KisService.saveCredentials('r-key', 'r-secret', '2222222202', false)

    // paper 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('p-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('1111111101')
    // real 신규 저장
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBe('r-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBe('r-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBe('2222222202')
  })
})

/**
 * hasCredentials 응답 형식 — boolean 단일 → 객체 (paper/real) 로 변경.
 */
describe('KisService.hasCredentials — 모드별 등록 여부 객체', () => {
  it('아무것도 등록되지 않음 → { paper: false, real: false }', async () => {
    const result = await KisService.hasCredentials()
    expect(result).toEqual({ paper: false, real: false })
  })

  it('paper 만 등록 → { paper: true, real: false }', async () => {
    await KisService.saveCredentials('k', 's', 'a', true)
    const result = await KisService.hasCredentials()
    expect(result).toEqual({ paper: true, real: false })
  })

  it('real 만 등록 → { paper: false, real: true }', async () => {
    await KisService.saveCredentials('k', 's', 'a', false)
    const result = await KisService.hasCredentials()
    expect(result).toEqual({ paper: false, real: true })
  })

  it('양쪽 모두 등록 → { paper: true, real: true }', async () => {
    await KisService.saveCredentials('pk', 'ps', 'pa', true)
    await KisService.saveCredentials('rk', 'rs', 'ra', false)
    const result = await KisService.hasCredentials()
    expect(result).toEqual({ paper: true, real: true })
  })

  it('한 모드의 키 일부만 누락 → 그 모드는 false (정확한 부분 등록 차단)', async () => {
    // appKey 와 appSecret 만 paper slot 에 — accountNo 누락
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'k')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 's')
    // accountNo 미등록

    const result = await KisService.hasCredentials()
    expect(result.paper).toBe(false)
    expect(result.real).toBe(false)
  })
})

/**
 * deleteCredentials — 특정 모드의 credential + 토큰 모두 삭제, 다른 모드는 보존.
 */
describe('KisService.deleteCredentials — 모드별 삭제', () => {
  it('paper 삭제 → paper credential + paper 토큰 모두 삭제, real 보존', async () => {
    // 양 모드 credential + 토큰 시드
    await KisService.saveCredentials('pk', 'ps', 'pa', true)
    await KisService.saveCredentials('rk', 'rs', 'ra', false)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'paper-token')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-paper',
      String(Date.now() + 86400_000),
    )
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-real', 'real-token')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-real',
      String(Date.now() + 86400_000),
    )

    await KisService.deleteCredentials(true) // paper 삭제

    // paper 모두 삭제
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper')).toBeNull()

    // real 모두 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBe('rk')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBe('rs')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBe('ra')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-real')).toBe('real-token')
  })

  it('real 삭제 → real credential + real 토큰 모두 삭제, paper 보존', async () => {
    await KisService.saveCredentials('pk', 'ps', 'pa', true)
    await KisService.saveCredentials('rk', 'rs', 'ra', false)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-real', 'real-token')

    await KisService.deleteCredentials(false)

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-real')).toBeNull()
    // paper 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('pk')
  })

  it('활성 모드 키 삭제 → 메모리 access token clear (재사용 차단)', async () => {
    mainState.setPaperTrading(true) // 활성 = paper
    mainState.setKisAccessToken('paper-runtime-token', 3600)
    expect(mainState.kisAccessToken).toBe('paper-runtime-token')

    await KisService.saveCredentials('pk', 'ps', 'pa', true)
    await KisService.deleteCredentials(true) // 활성 모드 키 삭제

    expect(mainState.kisAccessToken).toBeNull()
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('비활성 모드 키 삭제 → 메모리 access token 유지 (활성 모드 운영 영향 없음)', async () => {
    mainState.setPaperTrading(true) // 활성 = paper
    mainState.setKisAccessToken('paper-runtime-token', 3600)

    await KisService.saveCredentials('rk', 'rs', 'ra', false)
    await KisService.deleteCredentials(false) // 비활성(real) 모드 키 삭제

    // 활성 모드 메모리 토큰은 그대로
    expect(mainState.kisAccessToken).toBe('paper-runtime-token')
    expect(mainState.isKisTokenValid()).toBe(true)
  })
})

/**
 * A3 hotfix #1: saveCredentials 가 옛 token slot 도 항상 정리.
 * EGW00133 fallback 시 옛 키로 발급된 토큰이 부활하면 새 키와 결합되어 KIS 가 거부.
 * 따라서 키 [수정] 시 메모리 + keytar token slot 모두 무효화 필수.
 */
describe('KisService.saveCredentials — 옛 토큰 명시 무효화 (hotfix #1)', () => {
  it('활성 모드 키 저장 → 그 모드 token slot keytar 삭제 + 메모리 토큰 clear', async () => {
    mainState.setPaperTrading(true)
    mainState.setKisAccessToken('paper-old-token', 3600)

    // 사전에 keytar 에 옛 토큰이 박혀 있음
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'paper-old-token')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-paper',
      String(Date.now() + 86400_000),
    )

    // 활성 모드(paper) 키 저장
    await KisService.saveCredentials('new-key', 'new-secret', 'new-account', true)

    // keytar token slot 정리 — EGW00133 fallback 진입 시 옛 토큰 부활 차단
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-paper')).toBeNull()
    // 메모리 토큰도 clear
    expect(mainState.kisAccessToken).toBeNull()
    expect(mainState.isKisTokenValid()).toBe(false)
  })

  it('비활성 모드 키 저장 → 그 모드 token slot keytar 만 삭제, 활성 모드 메모리 토큰 보존', async () => {
    mainState.setPaperTrading(true) // 활성 = paper
    mainState.setKisAccessToken('paper-runtime-token', 3600)

    // 비활성 모드(real) 의 옛 토큰이 keytar 에 박혀 있음
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-real', 'real-old-token')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-real',
      String(Date.now() + 86400_000),
    )

    // 비활성(real) 키 저장
    await KisService.saveCredentials('new-r-key', 'new-r-secret', 'new-r-account', false)

    // real token slot 정리 — 다음 활성화 시 재발급 트리거되도록
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-real')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-tokenExpiresAt-real')).toBeNull()
    // 활성(paper) 메모리 토큰은 그대로 — 운영 영향 없음
    expect(mainState.kisAccessToken).toBe('paper-runtime-token')
    expect(mainState.isKisTokenValid()).toBe(true)
  })

  it('활성 모드 키 저장 → 다른 모드 token slot 은 손대지 않음 (분리 보장)', async () => {
    mainState.setPaperTrading(true)
    // 양 모드 모두 토큰 시드
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-paper', 'p-tok')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-paper',
      String(Date.now() + 86400_000),
    )
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accessToken-real', 'r-tok')
    await keytar.setPassword(
      KEYTAR_SERVICE,
      'kis-tokenExpiresAt-real',
      String(Date.now() + 86400_000),
    )

    await KisService.saveCredentials('pk', 'ps', 'pa', true)

    // paper(저장한 모드) 토큰 정리됨, real(반대 모드) 토큰 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accessToken-real')).toBe('r-tok')
  })
})

/**
 * A3: getMaskedCredentials — UI 카드 표시용 마스킹된 응답.
 * appSecret 은 절대 응답에 포함되지 않는다.
 */
describe('KisService.getMaskedCredentials — 모드별 마스킹 응답', () => {
  it('양쪽 모두 등록 → 양쪽 모두 마스킹된 응답', async () => {
    // appKey 16자 이상 / accountNo 8자 이상 (마스킹 prefix+suffix 노출 케이스)
    await KisService.saveCredentials('PSDK0123456789ABCD', 'p-secret', '5012345601', true)
    await KisService.saveCredentials('PSDK1111111122RRRR', 'r-secret', '8888888899', false)

    const result = await KisService.getMaskedCredentials()

    expect(result.paper).not.toBeNull()
    expect(result.real).not.toBeNull()
    expect(result.paper!.appKeyMasked).toBe('PSDK****ABCD')
    expect(result.paper!.accountNoMasked).toBe('5012****01')
    expect(result.real!.appKeyMasked).toBe('PSDK****RRRR')
    expect(result.real!.accountNoMasked).toBe('8888****99')
  })

  it('paper 만 등록 → paper 마스킹, real 은 null', async () => {
    await KisService.saveCredentials('PSDK0123456789ABCD', 'p-secret', '5012345601', true)

    const result = await KisService.getMaskedCredentials()

    expect(result.paper).toEqual({
      appKeyMasked: 'PSDK****ABCD',
      accountNoMasked: '5012****01',
    })
    expect(result.real).toBeNull()
  })

  it('real 만 등록 → real 마스킹, paper 는 null', async () => {
    await KisService.saveCredentials('PSDK1111111122RRRR', 'r-secret', '8888888899', false)

    const result = await KisService.getMaskedCredentials()

    expect(result.paper).toBeNull()
    expect(result.real).toEqual({
      appKeyMasked: 'PSDK****RRRR',
      accountNoMasked: '8888****99',
    })
  })

  it('양쪽 미등록 → 양쪽 null', async () => {
    const result = await KisService.getMaskedCredentials()
    expect(result.paper).toBeNull()
    expect(result.real).toBeNull()
  })

  it('appSecret 만 누락 → 마스킹 응답에는 영향 없음 (appSecret 등록 여부와 무관)', async () => {
    // 의도적으로 appKey/accountNo 만 채우고 appSecret 누락 — getMasked 는 hasCredentials 와 다름.
    await keytar.setPassword('EarningWhisperer', 'kis-appKey-paper', 'PSDK0123456789ABCD')
    await keytar.setPassword('EarningWhisperer', 'kis-accountNo-paper', '5012345601')

    const result = await KisService.getMaskedCredentials()
    // appSecret 누락 상태여도 appKey + accountNo 가 있으면 마스킹 응답은 채워진다.
    // (appSecret 노출은 어차피 응답에 없고, 사용자에게는 카드 표시가 등록 인디케이터로 작동.)
    expect(result.paper).toEqual({
      appKeyMasked: 'PSDK****ABCD',
      accountNoMasked: '5012****01',
    })
    expect(result.real).toBeNull()
  })

  it('appKey/accountNo 어느 하나라도 누락 → 그 모드는 null', async () => {
    await keytar.setPassword('EarningWhisperer', 'kis-appKey-paper', 'PSDK0123456789ABCD')
    // accountNo 누락
    const result = await KisService.getMaskedCredentials()
    expect(result.paper).toBeNull()
  })
})

describe('maskAppKey — 마스킹 형식 검증', () => {
  it('16자 정확히 → prefix4 + **** + suffix4', () => {
    expect(maskAppKey('PSDK0123456789CD')).toBe('PSDK****89CD')
  })

  it('16자 초과 → prefix4 + **** + suffix4 (중간 길이는 가려짐)', () => {
    expect(maskAppKey('PSDK0123456789ABCDEFGHIJ')).toBe('PSDK****GHIJ')
  })

  it('15자 → 전체 마스킹 (16자 미만)', () => {
    expect(maskAppKey('PSDK01234567890')).toBe('****')
  })

  it('8자 미만 → 전체 마스킹', () => {
    expect(maskAppKey('PSDK')).toBe('****')
  })

  it('빈 문자열 → 전체 마스킹', () => {
    expect(maskAppKey('')).toBe('****')
  })
})

describe('maskAccountNo — 마스킹 형식 검증', () => {
  it('10자 → prefix4 + **** + suffix2', () => {
    expect(maskAccountNo('5012345601')).toBe('5012****01')
  })

  it('8자 정확히 → prefix4 + **** + suffix2', () => {
    expect(maskAccountNo('50123456')).toBe('5012****56')
  })

  it('7자 → 전체 마스킹 (8자 미만)', () => {
    expect(maskAccountNo('5012345')).toBe('****')
  })

  it('빈 문자열 → 전체 마스킹', () => {
    expect(maskAccountNo('')).toBe('****')
  })
})

/**
 * migrateLegacyKeysIfNeeded — 단일 slot 자격증명 키도 모드별 slot 으로 이전.
 * 토큰 마이그레이션은 기존 검증 (paper 로 이전) 그대로.
 */
describe('migrateLegacyKeysIfNeeded — 자격증명 마이그레이션', () => {
  it('legacy 단일 slot + isPaperTrading flag 미설정 → paper slot 으로 이전 (디폴트)', async () => {
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'old-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'old-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', '9999999901')

    await migrateLegacyKeysIfNeeded()

    // paper slot 으로 이전
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('old-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('old-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('9999999901')

    // legacy 단일 slot 정리
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')).toBeNull()

    // real 은 비어있음
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
  })

  it("legacy 단일 slot + kis-isPaperTrading='0' → real slot 으로 이전", async () => {
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'real-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'real-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', '8888888801')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-isPaperTrading', '0')

    await migrateLegacyKeysIfNeeded()

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBe('real-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBe('real-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBe('8888888801')
    // paper 는 비어있음
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBeNull()
  })

  it("legacy 단일 slot + kis-isPaperTrading='1' → paper slot 으로 이전", async () => {
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'paper-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'paper-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', '7777777701')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-isPaperTrading', '1')

    await migrateLegacyKeysIfNeeded()

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('paper-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('7777777701')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
  })

  it('idempotent — 이미 모드 slot 에 키가 있으면 충돌 회피, legacy 만 정리', async () => {
    // 모드 slot 에 이미 새 키가 등록되어 있음
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'new-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 'new-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo-paper', 'new-account')
    // legacy 도 남아있음 (이전 버전 잔재)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'old-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'old-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', 'old-account')

    await migrateLegacyKeysIfNeeded()

    // 모드 slot 의 새 값은 보존 — legacy 가 덮어쓰지 않음
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('new-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('new-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('new-account')

    // legacy 만 정리
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')).toBeNull()
  })

  it('두 번 연속 호출해도 안전 (idempotent)', async () => {
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'k')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 's')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', 'a')

    await migrateLegacyKeysIfNeeded()
    await migrateLegacyKeysIfNeeded() // 두 번째는 no-op

    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('k')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
  })

  it('legacy 키 없음 → no-op', async () => {
    await migrateLegacyKeysIfNeeded()
    // 아무 slot 에도 값 없어야 함
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
  })

  /**
   * 양쪽 slot 모두 점유 + legacy 충돌 시 보존 규칙 확인 (review code #2).
   * 마이그레이션이 절대 모드 slot 의 기존 값을 덮어쓰지 않아야 한다.
   */
  it('paper/real 양쪽 slot + legacy 모두 존재 → 양쪽 보존, legacy 만 정리', async () => {
    // paper, real slot 모두 키 등록
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'A-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 'A-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo-paper', 'A-account')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-real', 'B-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-real', 'B-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo-real', 'B-account')
    // legacy 단일 slot 도 존재 (이전 버전 잔재)
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'C-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'C-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', 'C-account')

    await migrateLegacyKeysIfNeeded()

    // paper / real 모두 보존 — legacy 가 어느 쪽도 덮어쓰지 않음
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('A-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe('A-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe('A-account')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBe('B-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBe('B-secret')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBe('B-account')

    // legacy 만 정리
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')).toBeNull()
  })

  it("paper 만 선점 + legacy 다른 키 + flag='1' → 기존 paper 보존, legacy 삭제", async () => {
    // paper 만 선점
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'paper-existing')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 'paper-existing-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo-paper', 'paper-existing-account')
    // legacy 다른 키
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'legacy-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'legacy-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', 'legacy-account')
    // flag = paper
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-isPaperTrading', '1')

    await migrateLegacyKeysIfNeeded()

    // 기존 paper 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('paper-existing')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-paper')).toBe(
      'paper-existing-secret',
    )
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe(
      'paper-existing-account',
    )
    // real 은 비어있어야 (legacy 가 real 로 새지 않음 — flag=paper)
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBeNull()
    // legacy 정리
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret')).toBeNull()
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo')).toBeNull()
  })

  it("paper 만 선점 + legacy 다른 키 + flag='0' → real 로 legacy 이전, paper 보존", async () => {
    // paper 선점
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey-paper', 'paper-existing')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret-paper', 'paper-existing-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo-paper', 'paper-existing-account')
    // legacy 다른 키
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appKey', 'legacy-real-key')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-appSecret', 'legacy-real-secret')
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-accountNo', 'legacy-real-account')
    // flag = real
    await keytar.setPassword(KEYTAR_SERVICE, 'kis-isPaperTrading', '0')

    await migrateLegacyKeysIfNeeded()

    // paper 보존
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-paper')).toBe('paper-existing')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-paper')).toBe(
      'paper-existing-account',
    )
    // legacy → real 이전
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey-real')).toBe('legacy-real-key')
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appSecret-real')).toBe(
      'legacy-real-secret',
    )
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-accountNo-real')).toBe(
      'legacy-real-account',
    )
    // legacy 정리
    expect(await keytar.getPassword(KEYTAR_SERVICE, 'kis-appKey')).toBeNull()
  })
})
