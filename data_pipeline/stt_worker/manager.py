import subprocess
import os
import sys
import time

class EarningManager:
    def __init__(self):
        # 파이썬 가상환경 가동 경로 확보
        self.venv_python = "/home/dheorb/AProjects/Earning-Whisperer/.venv/bin/python"
        self.agent_script = "/home/dheorb/AProjects/Earning-Whisperer/data_pipeline/stt_worker/monitor.py"

    def create_virtual_audio_sink(self, ticker):
        """ 🎧 우분투 시스템에 이 기업 전용 가상 오디오 블랙홀(Sink) 생성 """
        sink_name = f"sink_{ticker}"
        print(f"⚙️ [Manager] {ticker} 전용 가상 오디오 장치 생성 중... ({sink_name})")
        
        # pactl 명령어로 가상 싱크 로드
        cmd = [
            "pactl", "load-module", "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description='Earning_{ticker}_Sink'"
        ]
        
        try:
            # 성공하면 생성된 모듈의 고유 ID 번호(예: 42)가 문자열로 반환됨
            module_id = subprocess.check_output(cmd).decode().strip()
            print(f"   -> ✅ 가상 싱크 생성 완료. (시스템 등록 ID: {module_id})")
            return module_id, sink_name
        except Exception as e:
            print(f"   -> ❌ 가상 싱크 생성 실패: {e}")
            return None, None

    def remove_virtual_audio_sink(self, module_id):
        """ 🧹 작전 종료 후 시스템 오디오 자원 반납 및 청소 """
        if not module_id:
            return
        print(f"🧹 [Manager] 사용이 끝난 가상 오디오 자원 반납 중... (ID: {module_id})")
        subprocess.run(["pactl", "unload-module", module_id], stdout=subprocess.DEVNULL)

    def launch_agent(self, ticker, url):
        """ 🚀 격리된 가상 오디오 환경 속으로 요원 프로세스 슈팅 및 실시간 무전 감시 """
        module_id, sink_name = self.create_virtual_audio_sink(ticker)
        if not sink_name:
            print("❌ 오디오 인프라 확보 실패로 작전을 취소합니다.")
            return False

        # 지휘관(Orchestrator)에게 보고할 최종 상주 상태 판정 플래그
        is_streaming_active = False
        try:
            print(f"📡 [Manager] 요원 격리 가동 -> 티커: {ticker} | 목표지: {url}")
            
            # 🔥 [핵심 치트키] 환경 변수에 PULSE_SINK를 주입하여 
            # 이 프로세스가 켜는 크로미움 브라우저의 소리를 가상 싱크로 강제 리다이렉트합니다.
            custom_env = os.environ.copy()
            custom_env["PULSE_SINK"] = sink_name
            
            # 💡 [보정 가동] 요원의 실시간 무전을 오케스트레이터가 가로챌 수 있도록 파이프 통로 개설
            process = subprocess.Popen(
                [self.venv_python, self.agent_script, ticker, url],
                env=custom_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # 📡 요원이 뱉어내는 로그 스트림을 마이크로초 단위로 실시간 인터셉트 수신
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                
                # 메인 콘솔 터미널에 요원의 웹 침투 로그 상황을 그대로 중계 출력
                sys.stdout.write(line)
                sys.stdout.flush()

                # 🎯 [판단] 요원이 본방 재생 버튼을 낚아채서 STT 무한 루프 도청망을 개통했을 때
                if "어닝콜 오디오 스트리밍 활성화 성공" in line:
                    is_streaming_active = True
                
                # 🎯 [판단] 방이 안 열려서 요원이 5초 만에 브라우저 끄고 자진 철수(먹튀)할 때
                if "정찰 종료" in line or "등록 폼 작성에 실패했습니다" in line:
                    is_streaming_active = False

            process.wait()
            print(f"🏁 [Manager] {ticker} 요원 미션 종료 및 복귀 확인.")

        except KeyboardInterrupt:
            print(f"\n⚠️ [Manager] 강제 정지 시그널 감지. {ticker} 요원 강제 철수 중...")
            process.terminate()
        finally:
            # 뚫어놓은 가상 오디오 장치는 임무 성패와 상관없이 무조건 완벽하게 폭파하여 자원을 수거합니다.
            self.remove_virtual_audio_sink(module_id)
            
        # 오케스트레이터에게 이번 침투가 허탕이었는지 상주 도청 성공이었는지 최종 성적표 상고
        return is_streaming_active

if __name__ == "__main__":
    # 스케줄러가 에어비앤비 어닝콜 타임을 감지해 던져줬다고 가정한 가동 매커니즘
    manager = EarningManager()
    
    mock_ticker = "ABNB"
    mock_url = "https://investors.airbnb.com/events-and-presentations/default.aspx"
    
    manager.launch_agent(mock_ticker, mock_url)