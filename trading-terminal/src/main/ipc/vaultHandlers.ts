import { KisService } from '../services/KisService'
import { KisWebSocketService } from '../services/KisWebSocketService'
import { mainState } from '../store/mainState'
import { IPC_CHANNELS, type MaskedCredentialsResponse } from '../../lib/ipcChannels'
import { IpcError } from '../../lib/types/ipcError'
import { registerHandler } from './registerHandler'

/**
 * 비어있지 않은 string 검증.
 * 공백만 있는 문자열 (`'   '`) 도 거부 — keytar 에 박히면 hasCredentials 가 등록됨으로
 * 오인하는 경로 차단 (truthy 한 빈 값이 자격증명 검증을 무력화하지 않도록).
 */
function assertNonBlankString(value: unknown, fieldName: string): asserts value is string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new IpcError('VALIDATION', `${fieldName} must be a non-empty string`)
  }
}

export function registerVaultHandlers() {
  registerHandler<
    {
      appKey: string
      appSecret: string
      accountNo: string
      isPaperTrading: boolean
      /** 선택. 실시간 체결통보 구독의 tr_key 로 쓰인다. */
      htsId?: string
    },
    { success: true }
  >(
    IPC_CHANNELS.VAULT_SAVE,
    async (_e, payload) => {
      // 입력 strict 검증 — settingsHandlers 의 boolean 검증 패턴 재사용.
      // truthy 값으로 우회하거나 빈 문자열을 keytar 에 박아 "등록됨" 으로 오인되는 경로 차단.
      if (typeof payload?.isPaperTrading !== 'boolean') {
        throw new IpcError('VALIDATION', 'isPaperTrading must be boolean')
      }
      // 수정 흐름에서는 빈 칸을 "기존 값 유지" 로 본다. appSecret 은 보안상 화면에 되돌려
      // 줄 수 없으므로, 빈 칸을 재입력 강제로 해석하면 HTS ID 하나 바꾸려고 비밀값을 전부
      // 다시 치게 된다. 신규 등록(기존 값 없음)일 때만 필수로 검증한다.
      const existing = await KisService.getCredentialsForEdit(payload.isPaperTrading)
      const appKeyIn = typeof payload?.appKey === 'string' ? payload.appKey.trim() : ''
      const appSecretIn = typeof payload?.appSecret === 'string' ? payload.appSecret.trim() : ''
      const accountNoIn = typeof payload?.accountNo === 'string' ? payload.accountNo.trim() : ''

      const resolvedAppKey = appKeyIn || existing.appKey
      const resolvedAppSecret = appSecretIn || existing.appSecret
      const resolvedAccountNo = accountNoIn || existing.accountNo

      assertNonBlankString(resolvedAppKey, 'appKey')
      assertNonBlankString(resolvedAppSecret, 'appSecret')
      assertNonBlankString(resolvedAccountNo, 'accountNo')

      // htsId 는 선택 입력 — 없으면 체결통보만 못 받고 나머지 기능은 정상이다.
      if (payload?.htsId !== undefined && typeof payload.htsId !== 'string') {
        throw new IpcError('VALIDATION', 'htsId must be a string')
      }
      const { isPaperTrading, htsId } = payload
      // 계좌번호 정규화 — '12345678-01' 처럼 구분자가 섞이면 ACNT_PRDT_CD 가 '-01' 로 나간다.
      //
      // 8자리(계좌번호만) 와 10자리(계좌 8 + 상품코드 2) 를 모두 받는다. KisService 의
      // parseAccountNo 가 `digits.slice(8) || '01'` 로 상품코드를 기본 적용하므로 8자리도
      // 정상 동작한다 — 실제로 8자리로 저장된 계좌로 주문이 계속 체결돼 왔다.
      // 10자리만 허용하던 이전 검증은 동작보다 엄격해서, 멀쩡한 계좌를 거부했다.
      const normalizedAccountNo = resolvedAccountNo.replace(/\D/g, '')
      if (normalizedAccountNo.length !== 8 && normalizedAccountNo.length !== 10) {
        // 자릿수를 함께 알려준다 — 빈 칸으로 두면 기존 값을 쓰는데, 그 기존 값이 걸리면
        // 입력한 적도 없는 필드가 실패해 원인을 알 수 없다. 계좌번호 자체는 노출하지 않는다.
        const source = accountNoIn ? '입력한 계좌번호' : '저장된 계좌번호'
        throw new IpcError(
          'VALIDATION',
          `계좌번호는 숫자 8자리(계좌번호) 또는 10자리(계좌 8 + 상품코드 2)여야 합니다. ` +
            `${source}는 숫자 ${normalizedAccountNo.length}자리입니다.`,
        )
      }
      await KisService.saveCredentials(
        resolvedAppKey,
        resolvedAppSecret,
        normalizedAccountNo,
        isPaperTrading,
        htsId,
      )
      // 활성 모드 자격증명이 바뀌면 WebSocket 도 다시 연결한다. 체결통보 구독은 연결
      // 시점에 HTS ID 를 tr_key 로 보내므로, 재연결하지 않으면 방금 등록한 HTS ID 가
      // 반영되지 않아 통보를 계속 못 받는다.
      if (isPaperTrading === mainState.isPaperTrading) {
        KisWebSocketService.disconnect()
        void KisWebSocketService.connectWithStoredKey()
      }

      // 저장 대상 모드와 현재 활성 모드가 일치할 때만 토큰 발급 시도.
      // 다른 모드 키 등록(예: paper 활성 상태에서 real 키 등록)은 발급 skip — A3 의 양쪽 등록 UX 지원.
      if (isPaperTrading === mainState.isPaperTrading) {
        try {
          await KisService.issueToken()
        } catch (e) {
          console.warn(
            '[Vault] 자격증명 저장 후 KIS 토큰 발급 실패:',
            e instanceof Error ? e.message : 'unknown error',
          )
        }
      }
      return { success: true }
    },
  )

  registerHandler<
    void,
    { paper: boolean; real: boolean; paperHtsId: boolean; realHtsId: boolean }
  >(
    IPC_CHANNELS.VAULT_HAS,
    async () => {
      return KisService.hasCredentials()
    },
  )

  registerHandler<void, MaskedCredentialsResponse>(
    IPC_CHANNELS.VAULT_GET_MASKED,
    async () => {
      // KisService 가 이미 appKey/accountNo 만 읽어 마스킹 처리 — appSecret 은 노출 X.
      // payload 는 void (인자 없음). 모드 양쪽을 한 번에 반환해 UI 가 별도 호출 줄임.
      return KisService.getMaskedCredentials()
    },
  )

  registerHandler<{ isPaperTrading: boolean }, { success: true }>(
    IPC_CHANNELS.VAULT_DELETE,
    async (_e, payload) => {
      // 삭제 대상 모드 strict 검증 — 임의 truthy 로 활성 모드와 다른 slot 이 지워지는 사고 방지.
      if (typeof payload?.isPaperTrading !== 'boolean') {
        throw new IpcError('VALIDATION', 'isPaperTrading must be boolean')
      }
      await KisService.deleteCredentials(payload.isPaperTrading)
      return { success: true }
    },
  )
}
