import asyncio
import json
import queue
import threading
import time
import websockets
from typing import Optional
import streamlit as st

class WebSocketClient:
    def __init__(self, base_uri: str = "ws://localhost:8000"):
        self.base_uri = base_uri
        self.websocket = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._message_queue: queue.Queue = queue.Queue()
        self._task_id: Optional[str] = None

    def connect(self, task_id: Optional[str] = None):
        if self._running:
            self.disconnect()
        self._task_id = task_id
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_event_loop(self):
        asyncio.run(self._listen())

    async def _listen(self):
        uri = f"{self.base_uri}/ws/{self._task_id}" if self._task_id else f"{self.base_uri}/ws"
        try:
            async with websockets.connect(uri, ping_interval=20) as ws:
                self.websocket = ws
                while self._running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        data = json.loads(msg)
                        self._message_queue.put(data)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
        except Exception as e:
            print(f"WebSocket error: {e}")

    def get_messages(self) -> list:
        messages = []
        while not self._message_queue.empty():
            try:
                messages.append(self._message_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def is_connected(self) -> bool:
        return self._running and self.websocket is not None

def process_incoming_messages() -> bool:
    ws_client = st.session_state.get("ws_client")
    if not ws_client or not ws_client.is_connected():
        return False
    new_msgs = ws_client.get_messages()
    if not new_msgs:
        return False
    messages_to_add = []
    for msg in new_msgs:
        msg_type = msg.get("type", "message")
        if msg_type == "progress":
            st.session_state.task_progress = msg.get("progress", 0)
            st.session_state.task_status = msg.get("status", "")
        elif msg_type == "log":
            logs = st.session_state.get("log_messages", [])
            logs.append(msg)
            st.session_state.log_messages = logs[-100:]
        else:
            messages_to_add.append({
                "sender_role": msg.get("sender_role", "system"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp", ""),
            })
    if messages_to_add:
        st.session_state.messages = st.session_state.get("messages", []) + messages_to_add
    return True