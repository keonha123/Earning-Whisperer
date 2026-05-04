# data_pipeline/stt_worker/manager.py
class STTWorkerManager:
    @staticmethod
    async def launch_mission(call):
        print(f"🚀 [STTWorker] {call['ticker']} 미션 준비 중... (미구현)")

# 스케듈러에서 monitor_and_trigger_stt 함수가 구현되면, 해당 함수에서 STTWorkerManager.launch_mission(call)을 호출하여
# 실시간으로 어닝콜이 시작하는 종목에 대해 STT 워커를 실행할 수 있도록 설계할 예정입니다.
# 1. 일단 이 부분에서 티켓정보와 기업정보그리고 일전에 discovery.py로 db에 저장한 ir_url을 가져와서
# 2. 실제 실행되는 영상의 주소를 확보한뒤
# 3. 해당 영상을 독립된 공간에서 재생시키고
# take.py를 호출하여 텍스트를 추출하는 형태의 구조입니다.
# 여기서 2번과 3번과정이 별개로 구성될지 아니면 동시에 이루어질지는 미정입니다.