package com.earningwhisperer.presentation.glossary;

import com.earningwhisperer.infrastructure.glossary.Glossary;
import com.earningwhisperer.infrastructure.glossary.GlossaryService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 어닝콜 용어 사전 조회 API.
 *
 * <p>Trading Terminal 이 앱 시작 시 한 번 받아 용어 하이라이팅에 쓴다. 인증은 기본 정책(JWT 필요)을 따른다.
 */
@RestController
@RequestMapping("/api/v1/glossary")
@RequiredArgsConstructor
public class GlossaryController {

    private final GlossaryService glossaryService;

    @GetMapping
    public ResponseEntity<Glossary> glossary() {
        return ResponseEntity.ok(glossaryService.glossary());
    }
}
