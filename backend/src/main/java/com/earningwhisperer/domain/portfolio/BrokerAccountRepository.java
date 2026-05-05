package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface BrokerAccountRepository extends JpaRepository<BrokerAccount, Long> {

    List<BrokerAccount> findByUserId(Long userId);

    Optional<BrokerAccount> findByUserIdAndBrokerAndIsPaper(Long userId, Broker broker, Boolean isPaper);
}
