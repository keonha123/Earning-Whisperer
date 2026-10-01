"use client";

import { useEffect, useRef } from "react";
import { Client, IMessage } from "@stomp/stompjs";
import SockJS from "sockjs-client";
import { useDemoStore } from "@/store/demoStore";

/**
 * 이 훅은 현재 백엔드에 연결되지 않는다.
 *
 * 백엔드가 인증되지 않은 STOMP 연결을 거부하도록 바뀌었는데(#136), 여기서는 CONNECT
 * 헤더에 토큰을 싣지 않는다. 그래서 연결이 거부되고 화면에 데이터가 들어오지 않는다.
 *
 * 토큰을 싣게 고치지 않은 것은 웹 개발이 보류 상태이고, 이 모듈에 로그인·토큰 보관
 * 흐름이 아직 없기 때문이다. 공개 토픽만 비인증으로 열어 두는 선택지도 있었지만
 * 그러면 누구나 분석 결과를 구독할 수 있는 상태가 그대로 남는다.
 *
 * 웹 개발을 재개할 때 로그인 흐름과 함께 CONNECT 헤더에 토큰을 싣는 작업이 필요하다.
 */
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "http://localhost:8080/ws";
const TOPIC_SIGNAL = "/topic/live/demo";
const TOPIC_PRICE = "/topic/live/demo/price";
const RECONNECT_DELAY_MS = 3000;

/**
 * 이 훅이 CONNECT 헤더에 토큰을 실을 수 있게 되면 true 로 바꾼다.
 * 그 전까지 연결은 백엔드에서 거부되므로 시도하지 않는다.
 */
const TOKEN_SUPPORTED = false;

export function useDemoWebSocket() {
  const clientRef = useRef<Client | null>(null);
  const { setConnected, receiveSignal, receivePrice } = useDemoStore();

  useEffect(() => {
    /*
     * 연결을 시도하지 않는다. 토큰을 싣지 않아 백엔드가 거부하는데, stompjs 는
     * reconnectDelay 간격으로 영원히 다시 붙으려 한다. 그대로 두면 이 페이지를 열어 둔
     * 동안 3초마다 세션이 생겼다 닫히고 서버 로그와 콘솔이 계속 쌓인다.
     *
     * 위 주석의 작업(로그인 흐름과 토큰 전달)을 하면서 이 가드를 걷어내면 된다.
     */
    if (!TOKEN_SUPPORTED) return;

    const client = new Client({
      webSocketFactory: () => new SockJS(WS_URL),
      reconnectDelay: RECONNECT_DELAY_MS,

      onConnect: () => {
        setConnected(true);

        client.subscribe(TOPIC_SIGNAL, (frame: IMessage) => {
          const msg = JSON.parse(frame.body);
          receiveSignal(msg);
        });

        client.subscribe(TOPIC_PRICE, (frame: IMessage) => {
          const msg = JSON.parse(frame.body);
          receivePrice(msg);
        });
      },

      onDisconnect: () => {
        setConnected(false);
      },

      onStompError: () => {
        setConnected(false);
      },
    });

    client.activate();
    clientRef.current = client;

    return () => {
      client.deactivate();
    };
  }, [setConnected, receiveSignal, receivePrice]);
}
