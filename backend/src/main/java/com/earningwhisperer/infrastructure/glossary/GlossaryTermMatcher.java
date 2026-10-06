package com.earningwhisperer.infrastructure.glossary;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 원문에서 사전 용어를 찾는다. 번역 요청에 실을 용어를 고를 때 쓴다(Contract 9.10).
 *
 * <ul>
 *   <li>대표 표기와 별칭을 모두 찾고, 대소문자는 가리지 않는다.</li>
 *   <li>단어 경계에서만 잡는다. {@code sales} 가 {@code wholesales} 안에서 잡히지 않는다.</li>
 *   <li>겹치면 긴 표기가 이긴다. "adjusted operating income" 이 잡힌 자리에서 "operating income" 을
 *       따로 잡지 않는다. 짧은 쪽까지 보내면 LLM 이 같은 구절에 번역어 두 개를 끼워 넣는다.</li>
 * </ul>
 */
public final class GlossaryTermMatcher {

    /** 원문에 나온 표기와 고정할 번역어. */
    public record Match(String spelling, String ko) {
    }

    private record Entry(String spelling, String ko, Pattern pattern) {
    }

    private final List<Entry> entries;

    public GlossaryTermMatcher(Glossary glossary) {
        List<Entry> built = new ArrayList<>();
        for (Glossary.Term term : glossary.terms()) {
            built.add(entry(term.term(), term.ko()));
            for (String alias : term.aliases()) {
                built.add(entry(alias, term.ko()));
            }
        }
        built.sort(Comparator.comparingInt((Entry e) -> e.spelling().length()).reversed());
        this.entries = List.copyOf(built);
    }

    /**
     * 원문에 나온 용어를 원문 순서대로 돌려준다. 같은 용어가 여러 번 나와도 한 번만 담는다.
     *
     * @param limit 최대 개수. 엔진 계약 상한(50)을 넘기지 않도록 호출자가 넘긴다.
     */
    public List<Match> find(String text, int limit) {
        if (text == null || text.isBlank() || limit <= 0) {
            return List.of();
        }
        boolean[] taken = new boolean[text.length()];
        Map<Integer, Match> byPosition = new TreeMap<>();
        for (Entry entry : entries) {
            Matcher m = entry.pattern().matcher(text);
            while (m.find()) {
                if (overlaps(taken, m.start(), m.end())) {
                    continue;
                }
                for (int i = m.start(); i < m.end(); i++) {
                    taken[i] = true;
                }
                byPosition.put(m.start(), new Match(m.group(), entry.ko()));
            }
        }
        // 같은 용어(번역어)는 원문에서 처음 나온 표기 하나만 남긴다.
        Set<String> seenKo = new HashSet<>();
        List<Match> matches = new ArrayList<>();
        for (Match match : byPosition.values()) {
            if (matches.size() >= limit) {
                break;
            }
            if (seenKo.add(match.ko())) {
                matches.add(match);
            }
        }
        return List.copyOf(matches);
    }

    private static Entry entry(String spelling, String ko) {
        Pattern pattern = Pattern.compile(
                "(?<![\\p{Alnum}])" + Pattern.quote(spelling) + "(?![\\p{Alnum}])",
                Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
        return new Entry(spelling, ko, pattern);
    }

    private static boolean overlaps(boolean[] taken, int start, int end) {
        for (int i = start; i < end; i++) {
            if (taken[i]) {
                return true;
            }
        }
        return false;
    }
}
