package com.earningwhisperer.infrastructure.glossary;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("GlossaryService 테스트")
class GlossaryServiceTest {

    /** 운영과 같은 조건 — Spring 기본 매퍼는 모르는 필드를 무시한다. 엄격 검사는 서비스가 직접 켠다. */
    private final ObjectMapper objectMapper = Jackson2ObjectMapperBuilder.json().build();

    @Test
    @DisplayName("패키징된 사전 파일이 규칙을 통과하고 시연 콜의 핵심 용어를 담고 있다")
    void 실제_사전_파일() {
        GlossaryService service = new GlossaryService(objectMapper, "data/glossary_ko.json");

        Glossary glossary = service.glossary();
        assertThat(glossary.version()).isPositive();
        assertThat(glossary.terms()).extracting(Glossary.Term::term)
                .contains("comp sales", "constant currency", "guidance", "basis points");
        assertThat(glossary.terms()).filteredOn(t -> t.term().equals("comp sales"))
                .singleElement()
                .satisfies(t -> {
                    assertThat(t.ko()).isEqualTo("기존점 매출");
                    assertThat(t.aliases()).contains("comps");
                });
    }

    @Test
    @DisplayName("패키징된 사전은 정의와 '왜 중요한가' 를 짝으로 갖고, 시연 콜 용어에 정의가 있다")
    void 실제_사전_정의() {
        Glossary glossary = new GlossaryService(objectMapper, "data/glossary_ko.json").glossary();

        // 정의만 있고 이유가 없거나 그 반대면 팝오버가 반쪽으로 뜬다.
        assertThat(glossary.terms()).allSatisfy(t ->
                assertThat(isBlank(t.definitionKo())).as(t.term()).isEqualTo(isBlank(t.whyKo())));
        assertThat(glossary.terms())
                .filteredOn(t -> List.of("comp sales", "guidance", "constant currency", "adjusted EPS", "basis points")
                        .contains(t.term()))
                .hasSize(5)
                .allSatisfy(t -> assertThat(t.definitionKo()).as(t.term()).isNotBlank());
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    @Test
    @DisplayName("없는 파일이면 기동을 실패시킨다")
    void 파일_없음() {
        assertThatThrownBy(() -> new GlossaryService(objectMapper, "data/no-such-glossary.json"))
                .hasMessageContaining("용어 사전을 읽지 못했습니다");
    }

    @Test
    @DisplayName("ko 가 비어 있으면 거부한다")
    void ko_누락() {
        Glossary parsed = glossary(term("comp sales", " ", "comps"));

        assertThatThrownBy(() -> GlossaryService.validate(parsed, "test"))
                .hasMessageContaining("term 과 ko 는 비어 있을 수 없습니다");
    }

    @Test
    @DisplayName("모르는 필드(키 오타)가 있으면 기동을 실패시킨다")
    void 모르는_필드() {
        assertThatThrownBy(() -> new GlossaryService(objectMapper, "glossary/unknown-field.json"))
                .hasMessageContaining("용어 사전을 읽지 못했습니다");
    }

    @Test
    @DisplayName("파일의 definition_ko · why_ko 를 읽고, 표기의 앞뒤 공백을 걷어낸다")
    void 정의_필드와_공백_정리() {
        Glossary glossary = new GlossaryService(objectMapper, "glossary/with-definition.json").glossary();

        assertThat(glossary.version()).isEqualTo(2);
        Glossary.Term t = glossary.terms().get(0);
        assertThat(t.term()).isEqualTo("comp sales");
        assertThat(t.aliases()).containsExactly("comps");
        assertThat(t.definitionKo()).startsWith("1년 이상");
        assertThat(t.whyKo()).isNotBlank();
    }

    @Test
    @DisplayName("terms 가 없거나 비어 있으면 거부한다")
    void terms_누락() {
        assertThatThrownBy(() -> GlossaryService.validate(new Glossary(1, null), "test"))
                .hasMessageContaining("terms 가 없습니다");
        assertThatThrownBy(() -> GlossaryService.validate(new Glossary(1, List.of()), "test"))
                .hasMessageContaining("terms 가 없습니다");
    }

    @Test
    @DisplayName("version 이 1 미만이면 거부한다")
    void version_누락() {
        assertThatThrownBy(() -> GlossaryService.validate(new Glossary(0, List.of(term("guidance", "가이던스"))), "test"))
                .hasMessageContaining("version");
    }

    @Test
    @DisplayName("한 표기가 두 용어에 걸리면 대소문자와 무관하게 거부한다")
    void 표기_중복() {
        Glossary parsed = glossary(
                term("comp sales", "기존점 매출", "Comps"),
                term("comps", "기존점 매출"));

        assertThatThrownBy(() -> GlossaryService.validate(parsed, "test"))
                .hasMessageContaining("같은 표기가 두 번 나옵니다");
    }

    @Test
    @DisplayName("앞뒤 공백만 다른 표기도 중복으로 거부한다")
    void 공백_중복() {
        Glossary parsed = glossary(
                term("comp sales", "기존점 매출", "comps "),
                term("comps", "기존점 매출"));

        assertThatThrownBy(() -> GlossaryService.validate(parsed, "test"))
                .hasMessageContaining("같은 표기가 두 번 나옵니다");
    }

    @Test
    @DisplayName("한 용어 안에서 term 과 alias 가 겹쳐도 거부한다")
    void 용어_내부_중복() {
        Glossary parsed = glossary(term("rollbacks", "한시 가격 인하", "Rollbacks"));

        assertThatThrownBy(() -> GlossaryService.validate(parsed, "test"))
                .hasMessageContaining("같은 표기가 두 번 나옵니다");
    }

    @Test
    @DisplayName("빈 alias 는 거부한다")
    void 빈_alias() {
        Glossary parsed = glossary(term("comp sales", "기존점 매출", ""));

        assertThatThrownBy(() -> GlossaryService.validate(parsed, "test"))
                .hasMessageContaining("빈 alias");
    }

    @Test
    @DisplayName("aliases 가 없으면 빈 목록으로 채우고 결과는 수정할 수 없다")
    void aliases_null() {
        Glossary parsed = new Glossary(1, Arrays.asList(
                new Glossary.Term("guidance", null, "가이던스", null, null, "guidance")));

        Glossary validated = GlossaryService.validate(parsed, "test");

        assertThat(validated.terms().get(0).aliases()).isEmpty();
        assertThatThrownBy(() -> validated.terms().add(null))
                .isInstanceOf(UnsupportedOperationException.class);
    }

    private static Glossary glossary(Glossary.Term... terms) {
        return new Glossary(1, List.of(terms));
    }

    private static Glossary.Term term(String term, String ko, String... aliases) {
        return new Glossary.Term(term, List.of(aliases), ko, null, null, "test");
    }
}
