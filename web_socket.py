# Enhanced WebSocketManager with audio support
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Union
import asyncio
import json
import base64
import time

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        print(f"[WS] Connected: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            print(f"[WS] Disconnected: {client_id}")

    async def send_text(self, client_id: str, message: str):
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                await websocket.send_text(message)
            except Exception as e:
                print(f"[WS] Error sending text to {client_id}: {e}")
                self.disconnect(client_id)

    async def send_json(self, client_id: str, data: Union[dict, list]):
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                await websocket.send_json(data)
            except Exception as e:
                print(f"[WS] Error sending JSON to {client_id}: {e}")
                self.disconnect(client_id)

    async def send_audio_buffer(self, client_id: str, audio_data: bytes, sample_rate: int = 16000, format: str = "pcm"):
        """Send raw audio buffer to specific client"""
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                # Send as binary data
                await websocket.send_bytes(audio_data)
            except Exception as e:
                print(f"[WS] Error sending audio buffer to {client_id}: {e}")
                self.disconnect(client_id)

    async def send_audio_json(self, client_id: str, audio_data: bytes, sample_rate: int = 16000, format: str = "pcm"):
        """Send audio as base64 encoded JSON message"""
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                audio_message = {
                    "type": "audio",
                    "data": base64.b64encode(audio_data).decode('utf-8'),
                    "sample_rate": sample_rate,
                    "format": format,
                    "timestamp": int(time.time() * 1000)
                }
                await websocket.send_json(audio_message)
            except Exception as e:
                print(f"[WS] Error sending audio JSON to {client_id}: {e}")
                self.disconnect(client_id)

    async def broadcast_audio_buffer(self, audio_data: bytes, sample_rate: int = 16000):
        """Broadcast raw audio buffer to all connected clients"""
        disconnected_clients = []
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_bytes(audio_data)
            except Exception as e:
                print(f"[WS] Error broadcasting audio to {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        for client_id in disconnected_clients:
            self.disconnect(client_id)

    async def broadcast_audio_json(self, audio_data: bytes, sample_rate: int = 16000, format: str = "pcm"):
        """Broadcast audio as base64 encoded JSON to all clients"""
        disconnected_clients = []
        
        audio_message = {
            "type": "audio",
            "data": base64.b64encode(audio_data).decode('utf-8'),
            "sample_rate": sample_rate,
            "format": format,
            "timestamp": int(time.time() * 1000)
        }
        
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(audio_message)
            except Exception as e:
                print(f"[WS] Error broadcasting audio JSON to {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        for client_id in disconnected_clients:
            self.disconnect(client_id)

    async def broadcast_text(self, message: str):
        disconnected_clients = []
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(message)
            except Exception as e:
                print(f"[WS] Error broadcasting text to {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        for client_id in disconnected_clients:
            self.disconnect(client_id)

    async def broadcast_json(self, data: Union[dict, list]):
        disconnected_clients = []
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(data)
            except Exception as e:
                print(f"[WS] Error broadcasting JSON to {client_id}: {e}")
                disconnected_clients.append(client_id)
        
        for client_id in disconnected_clients:
            self.disconnect(client_id)

    def get_client(self, client_id: str) -> Union[WebSocket, None]:
        return self.active_connections.get(client_id)
    
    def get_active_clients(self) -> list:
        return list(self.active_connections.keys())
    
    def is_connected(self, client_id: str) -> bool:
        return client_id in self.active_connections
        
ws_manager = WebSocketManager()
