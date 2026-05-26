package com.earningwhisperer.domain.portfolio;

import com.earningwhisperer.domain.user.User;
import com.earningwhisperer.domain.user.UserRepository;
import jakarta.persistence.EntityNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * BrokerAccount CRUD + 활성 전환 + 자동 provisioning.
 *
 * 사용자가 가입 직후엔 BrokerAccount 가 없을 수 있어, 첫 KIS 키 등록 시점이나 첫 sync 호출 시점에
 * 자동으로 BrokerAccount 가 생성되는 것이 자연스럽다. 본 서비스는 그 ensure 패턴을 제공한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BrokerAccountService {

    private final BrokerAccountRepository brokerAccountRepository;
    private final UserRepository userRepository;

    @Transactional(readOnly = true)
    public List<BrokerAccount> listByUser(Long userId) {
        return brokerAccountRepository.findByUserId(userId);
    }

    /**
     * 사용자의 활성 BrokerAccount 조회. 활성 식별자 미설정이거나 해당 row 가 없으면 empty.
     */
    @Transactional(readOnly = true)
    public Optional<BrokerAccount> getActive(Long userId) {
        Long activeId = userRepository.findById(userId)
                .map(User::getActiveBrokerAccountId)
                .orElse(null);
        if (activeId == null) return Optional.empty();
        return brokerAccountRepository.findById(activeId)
                .filter(acc -> acc.getUser().getId().equals(userId));
    }

    /**
     * accountType 에 해당하는 BrokerAccount 를 가져오거나, 없으면 자동 생성.
     * 첫 KIS 키 등록 / 첫 sync 시 호출자가 멱등하게 사용.
     */
    @Transactional
    public BrokerAccount ensure(Long userId, AccountType accountType) {
        return brokerAccountRepository.findByUserIdAndAccountType(userId, accountType)
                .orElseGet(() -> {
                    User user = userRepository.findById(userId)
                            .orElseThrow(() -> new EntityNotFoundException("User not found: " + userId));
                    BrokerAccount created = brokerAccountRepository.save(BrokerAccount.builder()
                            .user(user)
                            .accountType(accountType)
                            .build());
                    log.info("[BrokerAccountService] BrokerAccount 자동 생성 - userId={} accountType={} id={}",
                            userId, accountType, created.getId());
                    return created;
                });
    }

    /**
     * 활성 BrokerAccount 전환. 소유권 검증 + 활성 식별자 업데이트.
     */
    @Transactional
    public void switchActive(Long userId, Long brokerAccountId) {
        BrokerAccount account = brokerAccountRepository.findById(brokerAccountId)
                .orElseThrow(() -> new EntityNotFoundException(
                        "BrokerAccount not found: " + brokerAccountId));
        if (!account.getUser().getId().equals(userId)) {
            throw new SecurityException("BrokerAccount 소유권 불일치 - userId=" + userId
                    + " brokerAccountId=" + brokerAccountId);
        }
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new EntityNotFoundException("User not found: " + userId));
        user.switchActiveBrokerAccount(brokerAccountId);
        log.info("[BrokerAccountService] 활성 BrokerAccount 전환 - userId={} brokerAccountId={}",
                userId, brokerAccountId);
    }

    /**
     * 활성 BrokerAccount 가 미설정 상태이고 사용자 계정이 1개뿐이면 그것을 활성으로 set.
     * 첫 sync / 키 등록 후 자동 활성화 헬퍼.
     */
    @Transactional
    public void activateIfFirst(Long userId, Long brokerAccountId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new EntityNotFoundException("User not found: " + userId));
        if (user.getActiveBrokerAccountId() == null) {
            user.switchActiveBrokerAccount(brokerAccountId);
            log.info("[BrokerAccountService] 첫 BrokerAccount 자동 활성화 - userId={} brokerAccountId={}",
                    userId, brokerAccountId);
        }
    }

    /**
     * Terminal 의 잔고 sync — 해당 BrokerAccount 의 cashBalance 업데이트.
     */
    @Transactional
    public void syncCashBalance(Long userId, Long brokerAccountId, Double cashBalance) {
        BrokerAccount account = brokerAccountRepository.findById(brokerAccountId)
                .orElseThrow(() -> new EntityNotFoundException(
                        "BrokerAccount not found: " + brokerAccountId));
        if (!account.getUser().getId().equals(userId)) {
            throw new SecurityException("BrokerAccount 소유권 불일치");
        }
        account.syncCashBalance(cashBalance);
    }
}
