package com.earningwhisperer.infrastructure.redis;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.data.redis.listener.adapter.MessageListenerAdapter;
import org.springframework.data.redis.serializer.StringRedisSerializer;

@Configuration
public class RedisConfig {

    static final String MARKET_INDICES_CHANNEL = "market-indices";

    /**
     * 문자열 키/값 직렬화를 사용하는 RedisTemplate.
     * Redis에 JSON 문자열을 저장하거나 조회할 때 사용.
     */
    @Bean
    public RedisTemplate<String, String> redisTemplate(RedisConnectionFactory connectionFactory) {
        RedisTemplate<String, String> template = new RedisTemplate<>();
        template.setConnectionFactory(connectionFactory);
        template.setKeySerializer(new StringRedisSerializer());
        template.setValueSerializer(new StringRedisSerializer());
        template.setHashKeySerializer(new StringRedisSerializer());
        template.setHashValueSerializer(new StringRedisSerializer());
        return template;
    }

    /**
     * MarketIndicesSubscriber의 handleMessage() 메서드를 Redis 메시지 핸들러로 등록.
     */
    @Bean
    public MessageListenerAdapter marketIndicesListenerAdapter(MarketIndicesSubscriber subscriber) {
        return new MessageListenerAdapter(subscriber, "handleMessage");
    }

    /**
     * 리스너 컨테이너에 market-indices 채널을 등록한다.
     * ai-engine 이 여전히 trading-signals 채널에 발행할 수 있지만 매매 신호 경로를 제거해 구독하지 않는다.
     */
    @Bean
    public RedisMessageListenerContainer redisMessageListenerContainer(
            RedisConnectionFactory connectionFactory,
            MessageListenerAdapter marketIndicesListenerAdapter) {

        RedisMessageListenerContainer container = new RedisMessageListenerContainer();
        container.setConnectionFactory(connectionFactory);
        container.addMessageListener(
                marketIndicesListenerAdapter,
                new ChannelTopic(MARKET_INDICES_CHANNEL)
        );
        return container;
    }
}
