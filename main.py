
import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Dict
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI,WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from loguru import logger
from bot import run_bot
from pipecat.transports.network.webrtc_connection import IceServer, SmallWebRTCConnection
from fastapi.middleware.cors import CORSMiddleware
from web_socket import ws_manager


app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



pcs_map:Dict[str,SmallWebRTCConnection] = {}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    print(f"Attempting to connect: {client_id}")
    
    await ws_manager.connect(client_id, websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        print(f"Client {client_id} disconnected")
        ws_manager.disconnect(client_id)
    except Exception as e:
        print(f"Error with client {client_id}: {e}")
        ws_manager.disconnect(client_id)



ice_servers = [
    IceServer(
        urls="stun:stun.l.google.com:19302",
    )
]


@app.get("/")
def read_root():
    return FileResponse("index.html")

@app.get("/user")
def read_user():
    return FileResponse("user.html")



@app.post("/api/offer")
async def offer(request: dict, background_tasks: BackgroundTasks):
    pc_id = request.get("pc_id")

    if pc_id and pc_id in pcs_map:
        pipecat_connection = pcs_map[pc_id]
        logger.info(f"Reusing existing connection for pc_id: {pc_id}")
        await pipecat_connection.renegotiate(sdp=request["sdp"], type=request["type"])
    else:
        pipecat_connection = SmallWebRTCConnection(ice_servers)
        await pipecat_connection.initialize(sdp=request["sdp"], type=request["type"])
        @pipecat_connection.event_handler("closed")
        async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
            logger.info(f"Discarding peer connection for pc_id: {webrtc_connection.pc_id}")
            pcs_map.pop(webrtc_connection.pc_id, None)

        background_tasks.add_task(run_bot, pipecat_connection)

    answer = pipecat_connection.get_answer()
    # Updating the peer connection inside the map
    pcs_map[answer["pc_id"]] = pipecat_connection

    return answer

