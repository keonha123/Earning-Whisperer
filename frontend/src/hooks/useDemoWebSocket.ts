"use client";

import { useEffect, useRef } from "react";
import { Client, IMessage } from "@stomp/stompjs";
import SockJS from "sockjs-client";
import { useDemoStore } from "@/store/demoStore";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "http://localhost:8080/ws";
const TOPIC_SIGNAL = "/topic/live/demo";
const TOPIC_PRICE = "/topic/live/demo/price";
const RECONNECT_DELAY_MS = 3000;

export function useDemoWebSocket() {
  const clientRef = useRef<Client | null>(null);
  const { setConnected, receiveSignal, receivePrice } = useDemoStore();

  useEffect(() => {
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
