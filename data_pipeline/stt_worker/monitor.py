import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re
import subprocess
import numpy as np
from faster_whisper import WhisperModel
import sys
import time
import requests
import os

class EarningsAgent:
    def __init__(self, ticker, ir_url):
        self.ticker = ticker
        self.ir_url = ir_url
        self.sequence_counter = 0
        self.ai_engine_url = "http://localhost:8000/api/v1/analyze" 
        
        # 💡 [Q4 계정 설정] 본인의 실제 Q4 마스터 계정 정보를 주입하세요.
        self.investor_profile = {
            "email": "dheorbdheo@naver.com", 
            "password": "YOUR_Q4_PASSWORD_HERE",  
            "first_name": "Minsoo",
            "last_name": "Kim",
            "company": "Private Investor"
        }

        # 🎧 [오디오 장치 자동 매핑 인프라]
        if "PULSE_SINK" in os.environ:
            self.input_device = f"{os.environ['PULSE_SINK']}.monitor"
        else:
            self.input_device = "alsa_output.usb-Lenovo_Lenovo_Wireless_VoIP_Headset-Receiver_20230912.1-00.analog-stereo.monitor"

    async def monitor(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-user-gesture-required", "--autoplay-policy=no-user-gesture-required"]
            ) 
            try:
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 1000}, 
                    locale="en-US",
                    storage_state="q4_auth.json"
                )
                print("🎫 [인프라] Q4 프리패스 통행증(q4_auth.json) 장착 완료.")
            except:
                context = await browser.new_context(viewport={'width': 1280, 'height': 1000}, locale="en-US")
                print("⚠️ [인프라] 통행증 파일이 없어 맨몸 침투를 전개합니다.")

            page = await context.new_page()

            try:
                # -------------------------------------------------------------
                # [Stage 1] 대상 IR 페이지 접속 및 웹캐스트 경로 수색
                # -------------------------------------------------------------
                print(f"🚀 [{self.ticker}] 작전 시작: {self.ir_url}")
                await page.goto(self.ir_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2)

                found_el = await self.find_webcast_button(page)
                if not found_el:
                    print(f"❌ [{self.ticker}] 본문 영역 내 웹캐스트 링크를 찾을 수 없습니다.")
                    return False

                await found_el.scroll_into_view_if_needed()
                print(f"🎯 [{self.ticker}] 타겟 발견! 화면에 하이라이트 표시 후 4초간 대기합니다.")
                await found_el.evaluate("""el => {
                    el.style.outline = '10px solid red'; 
                    el.style.backgroundColor = 'yellow';
                    el.style.color = 'black';
                    el.style.zIndex = '9999';
                    el.style.position = 'relative';
                }""")
                await asyncio.sleep(4) 

                print(f"🖱️ [{self.ticker}] 링크 클릭 후 플레이어 페이지 진입 중...")
                target_page = page
                try:
                    async with context.expect_page(timeout=5000) as new_page_info:
                        await found_el.click(force=True)
                    target_page = await new_page_info.value
                    print(f"💡 [{self.ticker}] 플레이어가 새 탭에서 열렸습니다. 제어권을 전환합니다.")
                except PlaywrightTimeoutError:
                    print(f"💡 [{self.ticker}] 새 탭 팝업이 없습니다. 현재 창에서 전개합니다.")

                await target_page.wait_for_load_state("domcontentloaded")

                # -------------------------------------------------------------
                # [Stage 2] 양식 처리 레이어 (자율 예외 흡수 모드)
                # -------------------------------------------------------------
                form_success = await self.fill_registration_form(target_page)
                if not form_success:
                    print(f"❌ [{self.ticker}] 가입 폼 제어 도중 실시간 락(Lock)에 걸렸습니다.")
                    return False
                print(f"🚀 [{self.ticker}] 양식 검증 파트 통과 (가입 완료 혹은 자동 패스).")

                # -------------------------------------------------------------
                # [Stage 3] 미디어 플레이어 오디오 강제 개통 트리거 (정밀 대기형)
                # -------------------------------------------------------------
                playback_success = await self.trigger_media_playback(target_page)
                if playback_success:
                    print(f"🎧 [{self.ticker}] 어닝콜 오디오 스트리밍 룸 진입 성공!")
                else:
                    print(f"⚠️ [{self.ticker}] 미디어 강제 재생 트리거 유보. 스트림 소리 수집을 바로 시도합니다.")

                # 세션 백업서 저장
                await context.storage_state(path="q4_auth.json")

                # -------------------------------------------------------------
                # [Stage 4] 실시간 무손실 오디오 STT 추출 루프 기동
                # -------------------------------------------------------------
                print(f"\n📦 [{self.ticker}] 가상 오디오 장치 기반 STT 엔진 연동 중...")
                print(f"📡 [도청 타겟 장치]: {self.input_device}")
                
                stt_model = WhisperModel("distil-large-v3", device="cpu", compute_type="int8", cpu_threads=16)

                ffmpeg_cmd = [
                    'ffmpeg', '-f', 'pulse', '-i', self.input_device,
                    '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1'
                ]
                audio_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                print(f"🔥 'Earning Whisperer' 무손실 오디오 슬라이싱 무전망 개통 완료")
                print("=" * 70)

                audio_buffer = np.array([], dtype=np.float32)

                while True:
                    raw_audio = audio_process.stdout.read(64000)
                    if not raw_audio: 
                        break

                    audio_chunk = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
                    audio_buffer = np.append(audio_buffer, audio_chunk)
                    accumulated_seconds = len(audio_buffer) / 16000

                    segments, _ = stt_model.transcribe(audio_buffer, beam_size=1, language="en", vad_filter=True)
                    segment_list = list(segments)

                    full_text = " ".join([s.text.strip() for s in segment_list]).strip()
                    sys.stdout.write(f"\r\033[K[📡 실시간 문맥 교정 중] {full_text}")
                    sys.stdout.flush()

                    last_completed_idx = -1
                    for i, seg in enumerate(segment_list):
                        txt = seg.text.strip()
                        if txt and txt[-1] in ['.', '?', '!']:
                            last_completed_idx = i

                    if (accumulated_seconds >= 10.0 and last_completed_idx != -1) or (accumulated_seconds >= 20.0):
                        if last_completed_idx != -1:
                            completed_segments = segment_list[:last_completed_idx + 1]
                            chunk_to_send = " ".join([s.text.strip() for s in completed_segments]).strip()
                            slice_timestamp = segment_list[last_completed_idx].end
                            samples_to_drop = int(slice_timestamp * 16000)
                            audio_buffer = audio_buffer[samples_to_drop:]
                        else:
                            chunk_to_send = full_text
                            audio_buffer = np.array([], dtype=np.float32)

                        if chunk_to_send:
                            contract_payload = {
                                "ticker": self.ticker,
                                "text_chunk": chunk_to_send,
                                "sequence": self.sequence_counter,
                                "timestamp": int(time.time()),
                                "is_final": False
                            }

                            print("\n\n" + "✨"*5 + f" [무손실 오디오 마감 전송 # {self.sequence_counter}] " + "✨"*5)
                            print(f"💬 본문: {contract_payload['text_chunk']}")
                            
                            try:
                                response = requests.post(self.ai_engine_url, json=contract_payload, timeout=2)
                                if response.status_code == 200:
                                    print(f"📡 [FastAPI 기지국] 전송 ACK 승인 완료 -> {response.json()}")
                            except Exception as e:
                                print(f"❌ [통신 실패] {e}")
                                
                            print("-" * 70 + "\n")
                            self.sequence_counter += 1

            except KeyboardInterrupt:
                print("\n\n⚠️ [시그널] 종료 명령 확인. 잔여 오디오 청크 긴급 수송 가동...")
                try:
                    if len(audio_buffer) > 0:
                        segments, _ = stt_model.transcribe(audio_buffer, beam_size=1, language="en", vad_filter=True)
                        final_text = " ".join([s.text.strip() for s in segments]).strip()
                        if final_text:
                            final_payload = {
                                "ticker": self.ticker,
                                "text_chunk": final_text,
                                "sequence": self.sequence_counter,
                                "timestamp": int(time.time()),
                                "is_final": True
                            }
                            requests.post(self.ai_engine_url, json=final_payload, timeout=2)
                    print("🏁 자율 무전망 파이프라인 안전 종료 완료.")
                except:
                    pass
            except Exception as e:
                print(f"❌ [{self.ticker}] 시스템 치명적 결함 발생: {str(e)}")
            finally:
                try:
                    audio_process.terminate()
                except:
                    pass
                await browser.close()

    async def find_webcast_button(self, page):
        for frame in page.frames:
            candidates = frame.locator("a, button, [role='button']").filter(
                has_text=re.compile(r"Webcast|Listen|Join|Audio", re.IGNORECASE)
            )
            count = await candidates.count()
            for i in range(count):
                candidate = candidates.nth(i)
                is_menu_element = await candidate.evaluate("""el => {
                    let parent = el.parentElement;
                    while (parent) {
                        const tagName = parent.tagName.toLowerCase();
                        const className = parent.className ? String(parent.className).toLowerCase() : '';
                        const idName = parent.id ? String(parent.id).toLowerCase() : '';
                        if (
                            tagName === 'nav' || tagName === 'header' || tagName === 'footer' ||
                            className.includes('nav') || className.includes('menu') || className.includes('sidebar') ||
                            idName.includes('nav') || idName.includes('sidebar')
                        ) { return true; }
                        parent = parent.parentElement;
                    }
                    return false;
                }""")
                if is_menu_element or not await candidate.is_visible():
                    continue
                return candidate
        return None

    async def fill_registration_form(self, page):
        """ 🏰 [유연성 극대화 패치] 가입 폼이 없으면 에러가 아니라 프리패스로 인정하고 전진! """
        print(f"📝 [{self.ticker}] 가입/인증 폼 레이더망 가동...")
        
        selectors_to_wait = [
            "button#registration-box_signup-button",
            "input#email",
            "input#password",
            "form#fmRegister",
            "input[placeholder*='First' i]"
        ]
        combined_selectors = ", ".join(selectors_to_wait)
        
        try:
            print("    -> ⏳ 웹페이지 컴포넌트 렌더링 동기화 대기 중 (최대 10초)...")
            await page.wait_for_selector(combined_selectors, state="visible", timeout=10000)
            print("    -> ✅ 가입/로그인 관련 인터페이스 감지 완료.")
        except PlaywrightTimeoutError:
            # 🔥 [인사이트 반영 핵심 파트] 10초간 양식창이 하나도 안 떴다면?
            # 캐시로 이미 통과했거나, 애초에 로그인 장벽이 없는 다이렉트 패스 사이트입니다!
            print("    -> 🎉 [프리패스 시스템 감지] 제한시간 동안 가입 폼이 발견되지 않았습니다.")
            print("    -> 캐시 세션 로그인 상태이거나 직통 스트리밍 사이트입니다. 과감하게 다음 단계로 전진합니다.")
            return True # 에러를 내지 않고 대성공(True)을 반환하여 파이프라인을 유지합니다.

        # OneTrust 소탕
        try:
            onetrust_close = page.locator(".onetrust-close-btn-handler, #onetrust-accept-btn-handler").first
            if await onetrust_close.count() > 0 and await onetrust_close.is_visible():
                await onetrust_close.click(force=True)
                await asyncio.sleep(1)
        except:
            pass

        try:
            # ① Q4 프리 랜딩 게이트 처리
            q4_gate_button = page.locator("button#registration-box_signup-button, button:has-text('Register with a Q4 Account')").first
            if await q4_gate_button.count() > 0 and await q4_gate_button.is_visible():
                print(f"🏰 [{self.ticker}] Q4 프리 랜딩 게이트 통과 작동.")
                await q4_gate_button.click(force=True)
                await page.wait_for_selector("input#email", state="visible", timeout=10000)

            # ② Q4 1단계: 이메일 처리
            q4_email_field = page.locator("input#email").first
            q4_next_button = page.locator("button").filter(has_text=re.compile(r"^Next$", re.IGNORECASE)).first
            
            if await q4_email_field.count() > 0 and await q4_email_field.is_visible():
                print(f"🛡️ [{self.ticker}] Q4 이메일 기입: {self.investor_profile['email']}")
                await q4_email_field.fill(self.investor_profile["email"])
                await asyncio.sleep(0.5)
                await q4_next_button.click(force=True)
                await page.wait_for_selector("input#password", state="visible", timeout=10000)

            # ③ Q4 2단계: 패스워드 처리
            q4_password_field = page.locator("input#password").first
            q4_login_button = page.locator("button").filter(has_text=re.compile(r"^Log in$", re.IGNORECASE)).first

            if await q4_password_field.count() > 0 and await q4_password_field.is_visible():
                print(f"🔐 [{self.ticker}] Q4 패스워드 주입 및 최종 성문 개방.")
                await q4_password_field.fill(self.investor_profile["password"])
                await asyncio.sleep(0.5)
                if await q4_login_button.is_visible():
                    await q4_login_button.click(force=True)
                    await asyncio.sleep(5)
                    return True

            # ④ 구형 표준 가입 폼 백업 레이어
            container_selectors = ["form#fmRegister", "form[id*='reg' i]", "div[id*='reg' i]", "div[class*='form' i]"]
            container = None
            for c_sel in container_selectors:
                loc = page.locator(c_sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    container = loc
                    break
            root = container if container else page

            async def fill_field_by_label(label_text, value, fallbacks):
                try:
                    loc = root.get_by_label(label_text, exact=False)
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.fill(value)
                        return True
                except:
                    pass
                for sel in fallbacks:
                    loc = root.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.fill(value)
                        return True
                return False

            has_fields = await fill_field_by_label("First Name", self.investor_profile["first_name"], ["input[title*='First']", "input[name*='first']"])
            await fill_field_by_label("Last Name", self.investor_profile["last_name"], ["input[title*='Last']", "input[name*='last']"])
            await fill_field_by_label("Company", self.investor_profile["company"], ["input[title*='Company']", "input[name*='company']"])
            await fill_field_by_label("Email", self.investor_profile["email"], ["input[type='email']", "input[title*='Email']"])

            if has_fields:
                submit_btn = root.locator("input[type='submit'], button[type='submit'], button").filter(
                    has_text=re.compile(r"Submit|Register|Enter|Join", re.IGNORECASE)
                ).first
                if await submit_btn.count() > 0 and await submit_btn.is_visible():
                    await asyncio.sleep(1) 
                    await submit_btn.click(force=True)
                    print("    -> [제출 완료] 일반 가입 성문 돌파 완료!")
                    return True
            
            return True

        except Exception as e:
            print(f"⚠️ [{self.ticker}] 등록 폼 제어 중 예외 발생: {str(e)}")
            return False

    async def trigger_media_playback(self, page):
        """ 🎵 [고도화 패치] 로그인 우회 직후 로딩 애니메이션 등을 고려하여 재생 버튼이 보일 때까지 정밀 대기 """
        print(f"🎵 [{self.ticker}] 오디오 스트리밍 가로채기 파이프 개통 준비 중...")
        
        # 재생 버튼 후보군이 화면에 그릴 때까지 최대 8초간 동기화 대기
        try:
            play_selector = "button, a, div[role='button']"
            await page.wait_for_selector(play_selector, state="visible", timeout=8000)
        except:
            pass

        try:
            play_buttons = page.locator("button, a, div[role='button']").filter(
                has_text=re.compile(r"Play|Listen|Start|Unmute|▶", re.IGNORECASE)
            )
            btn_count = await play_buttons.count()
            for i in range(btn_count):
                btn = play_buttons.nth(i)
                if await btn.is_visible():
                    print(f"    -> [미디어 플레이어 작동] 재생 버튼 강제 클릭 완료 (#{i})")
                    await btn.click(force=True)
                    return True
            
            # 버튼이 렌더링에 실패했으나 오디오 객체가 내부에 심어져 있다면 자바스크립트로 강제 구동
            await page.evaluate("() => { const media = document.querySelector('video, audio'); if(media) { media.muted = false; media.play(); } }")
            return True
        except Exception as e:
            print(f"⚠️ [{self.ticker}] 미디어 강제 구동 유보: {str(e)[:40]}")
            return False

if __name__ == "__main__":
    target_ticker = sys.argv[1] if len(sys.argv) > 1 else "ABNB"
    target_url = sys.argv[2] if len(sys.argv) > 2 else "https://investors.airbnb.com" 
    
    agent = EarningsAgent(target_ticker, target_url)
    asyncio.run(agent.monitor())