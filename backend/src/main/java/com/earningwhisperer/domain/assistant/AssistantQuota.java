package com.earningwhisperer.domain.assistant;

import java.time.Duration;
import java.time.LocalDate;

/** 질의응답 사용 한도. 사용자별 하루 횟수와 동시 질문 1개를 다룬다. */
public interface AssistantQuota {

    /**
     * 그날 사용 횟수를 1 늘리고 한도 안이면 true. 질문을 시작할 때 차감하며, 답이 실패해도 돌려주지 않는다.
     * 한도를 넘은 요청도 횟수는 늘어나지만 결과(거부)는 같다.
     */
    boolean tryConsumeDaily(Long userId, LocalDate day, int limit);

    /** 진행 중인 질문이 없으면 잠그고 true. ttl 이 지나면 저절로 풀린다(중계가 비정상 종료한 경우 대비). */
    boolean tryLock(Long userId, Duration ttl);

    void unlock(Long userId);
}
