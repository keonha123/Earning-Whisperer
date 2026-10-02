package com.earningwhisperer.infrastructure.glossary;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 용어 사전 제공.
 *
 * <p>사전은 애플리케이션에 함께 패키징되는 리소스라 기동 시 한 번 읽고 끝까지 같은 값을 쓴다.
 * 파일이 깨졌거나 규칙을 어기면 <b>기동을 실패시킨다</b>. 빈 사전이나 잘못된 사전으로 조용히 떠 버리면
 * 번역이 용어 고정 없이 도는데, 화면만 봐서는 원인을 알 수 없다.
 */
@Slf4j
@Service
public class GlossaryService {

    private final Glossary glossary;

    public GlossaryService(
            ObjectMapper objectMapper,
            @Value("${glossary.path:data/glossary_ko.json}") String path) {
        this.glossary = load(objectMapper, path);
        log.info("[Glossary] 용어 사전 로드 - path={} version={} terms={}",
                path, glossary.version(), glossary.terms().size());
    }

    public Glossary glossary() {
        return glossary;
    }

    /** Prefer the longest spelling at each occurrence, without matching inside words. */
    public List<Glossary.Term> matchingTerms(String text) {
        record Match(int start, int end, Glossary.Term term) {}
        List<Match> matches = new ArrayList<>();
        for (Glossary.Term term : glossary.terms()) {
            List<String> spellings = new ArrayList<>(term.aliases());
            spellings.add(term.term());
            for (String spelling : spellings) {
                var matcher = java.util.regex.Pattern.compile("(?<![\\p{L}\\p{N}_])"
                        + java.util.regex.Pattern.quote(spelling) + "(?![\\p{L}\\p{N}_])",
                        java.util.regex.Pattern.CASE_INSENSITIVE | java.util.regex.Pattern.UNICODE_CASE).matcher(text);
                while (matcher.find()) matches.add(new Match(matcher.start(), matcher.end(), term));
            }
        }
        matches.sort(java.util.Comparator.comparingInt((Match m) -> m.end() - m.start()).reversed()
                .thenComparingInt(Match::start));
        List<Match> accepted = new ArrayList<>();
        for (Match match : matches) {
            if (accepted.stream().noneMatch(m -> match.start() < m.end() && m.start() < match.end()))
                accepted.add(match);
        }
        accepted.sort(java.util.Comparator.comparingInt(Match::start));
        return accepted.stream().map(Match::term).distinct().toList();
    }

    /**
     * 모르는 필드는 거부한다. Spring 기본 매퍼는 무시하므로, {@code definiton_ko} 같은 키 오타가
     * 조용히 버려져 정의가 빠진 채로 기동된다.
     */
    private static Glossary load(ObjectMapper objectMapper, String path) {
        Glossary parsed;
        try (InputStream in = new ClassPathResource(path).getInputStream()) {
            parsed = objectMapper.readerFor(Glossary.class)
                    .with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                    .readValue(in);
        } catch (IOException e) {
            throw new UncheckedIOException("용어 사전을 읽지 못했습니다: " + path, e);
        }
        return validate(parsed, path);
    }

    /**
     * 규칙 검증 후 앞뒤 공백을 걷어낸 불변 사본을 돌려준다.
     *
     * <ul>
     *   <li>{@code version} 은 1 이상, {@code terms} 는 1개 이상이어야 한다.</li>
     *   <li>{@code term} · {@code ko} 는 비어 있을 수 없다.</li>
     *   <li>{@code term} 과 {@code aliases} 전체에서 같은 표기(대소문자 · 앞뒤 공백 무시)가 두 번 나올 수 없다.
     *       한 표기가 두 용어에 걸리면 어느 번역어로 고정할지 정해지지 않는다.</li>
     * </ul>
     */
    static Glossary validate(Glossary parsed, String path) {
        if (parsed == null || parsed.terms() == null || parsed.terms().isEmpty()) {
            throw new IllegalStateException("용어 사전에 terms 가 없습니다: " + path);
        }
        if (parsed.version() < 1) {
            throw new IllegalStateException("용어 사전 version 은 1 이상이어야 합니다: " + path);
        }
        Map<String, String> owners = new HashMap<>();
        List<Glossary.Term> terms = new ArrayList<>(parsed.terms().size());
        for (Glossary.Term t : parsed.terms()) {
            if (t == null || isBlank(t.term()) || isBlank(t.ko())) {
                throw new IllegalStateException("term 과 ko 는 비어 있을 수 없습니다: " + t);
            }
            String term = t.term().strip();
            List<String> aliases = new ArrayList<>();
            if (t.aliases() != null) {
                for (String alias : t.aliases()) {
                    if (isBlank(alias)) {
                        throw new IllegalStateException("빈 alias 가 있습니다: " + term);
                    }
                    aliases.add(alias.strip());
                }
            }
            List<String> spellings = new ArrayList<>(aliases.size() + 1);
            spellings.add(term);
            spellings.addAll(aliases);
            for (String spelling : spellings) {
                String owner = owners.putIfAbsent(spelling.toLowerCase(Locale.ROOT), term);
                if (owner != null) {
                    throw new IllegalStateException(
                            "같은 표기가 두 번 나옵니다: '" + spelling + "' (" + owner + ", " + term + ")");
                }
            }
            terms.add(new Glossary.Term(
                    term, List.copyOf(aliases), t.ko().strip(), t.definitionKo(), t.whyKo(), t.category()));
        }
        return new Glossary(parsed.version(), List.copyOf(terms));
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
