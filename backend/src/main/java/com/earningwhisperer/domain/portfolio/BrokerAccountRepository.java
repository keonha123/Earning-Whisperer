package com.earningwhisperer.domain.portfolio;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;
import java.util.Optional;

public interface BrokerAccountRepository extends JpaRepository<BrokerAccount, Long> {

    List<BrokerAccount> findByUserId(Long userId);

    Optional<BrokerAccount> findByUserIdAndBrokerAndIsPaper(Long userId, Broker broker, Boolean isPaper);

    @Query("SELECT ba FROM BrokerAccount ba JOIN FETCH ba.user")
    List<BrokerAccount> findAllWithUser();
}
