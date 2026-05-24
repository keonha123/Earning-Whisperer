package com.earningwhisperer.domain.portfolio;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.List;

/**
 * 일별 총자산 스냅샷의 저장·조회 담당.
 *
 * <p>totalAsset = cashBalance + 보유 포지션 매입 평균가 기반 평가금액 합산.
 * 시세 기반 평가가 아닌 보수적 근사치임에 유의.
 */
@Service
@RequiredArgsConstructor
public class AssetSnapshotService {

    private final AssetDailySnapshotRepository snapshotRepository;
    private final PositionRepository positionRepository;

    /**
     * 특정 사용자의 오늘 스냅샷을 upsert 한다.
     *
     * @param userId         대상 사용자 ID
     * @param brokerAccountId 활성 BrokerAccount ID (포지션 조회에 사용)
     * @param cashBalance    현재 예수금 (null 이면 0 으로 처리)
     * @param date           스냅샷 기준일
     */
    @Transactional
    public void upsert(Long userId, Long brokerAccountId, Double cashBalance, LocalDate date) {
        double cash = cashBalance != null ? cashBalance : 0.0;
        double positionValue = positionRepository.findByBrokerAccountId(brokerAccountId)
                .stream()
                .mapToDouble(Position::bookValue)
                .sum();
        double total = cash + positionValue;

        snapshotRepository.findByUserIdAndSnapshotDate(userId, date)
                .ifPresentOrElse(
                        existing -> existing.update(total),
                        () -> snapshotRepository.save(
                                AssetDailySnapshot.builder()
                                        .userId(userId)
                                        .snapshotDate(date)
                                        .totalAsset(total)
                                        .build()));
    }

    /**
     * 특정 사용자의 자산 히스토리 조회.
     *
     * @param userId 대상 사용자 ID
     * @param from   조회 시작일 (inclusive)
     * @param to     조회 종료일 (inclusive)
     * @return 날짜 오름차순 포인트 목록
     */
    @Transactional(readOnly = true)
    public List<AssetHistoryPoint> getHistory(Long userId, LocalDate from, LocalDate to) {
        return snapshotRepository
                .findByUserIdAndSnapshotDateBetweenOrderBySnapshotDateAsc(userId, from, to)
                .stream()
                .map(s -> new AssetHistoryPoint(s.getSnapshotDate().toString(), s.getTotalAsset()))
                .toList();
    }

    public record AssetHistoryPoint(String date, Double totalAssetUsd) {}
}
