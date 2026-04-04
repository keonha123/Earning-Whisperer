package com.earningwhisperer.domain.stock;

import com.earningwhisperer.global.common.BaseEntity;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Entity
@Table(name = "stocks")
public class Stock extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 10)
    private String ticker;

    @Column(nullable = false)
    private String companyName;

    @Column(length = 50)
    private String sector;

    @Column(nullable = false)
    private boolean active = true;

    @Builder
    public Stock(String ticker, String companyName, String sector) {
        this.ticker = ticker;
        this.companyName = companyName;
        this.sector = sector;
        this.active = true;
    }

    public void deactivate() {
        this.active = false;
    }

    public void reactivate(String companyName, String sector) {
        this.active = true;
        this.companyName = companyName;
        this.sector = sector;
    }
}
