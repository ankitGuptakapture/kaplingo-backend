
import argparse
import asyncio
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from loguru import logger
from bot import run_bot
from bidirectional_bot import run_bidirectional_bot
from room_manager import room_manager, UserLanguage
from web_socket import ws_manager
from pipecat.transports.network.webrtc_connection import IceServer, SmallWebRTCConnection
from fastapi.middleware.cors import CORSMiddleware

pcs_map:Dict[str,SmallWebRTCConnection] = {}
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
ice_servers = [
    IceServer(
        urls="stun:stun.l.google.com:19302",
    )
]


@app.get("/")
def read_root():
    return FileResponse("index.html")

@app.get("/bidirectional.html")
def bidirectional_page():
    return FileResponse("bidirectional.html")



# Legacy single-user translation endpoint
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

# Bidirectional translation endpoints
@app.post("/api/join-room")
async def join_translation_room(request: dict):
    """Join or create a translation room"""
    try:
        user_id = request.get("user_id")
        preferred_language = request.get("language", "en")
        
        if not user_id:
            user_id = str(uuid.uuid4())
        
        # Convert language string to enum
        try:
            user_language = UserLanguage(preferred_language)
        except ValueError:
            user_language = UserLanguage.AUTO_DETECT
        
        # Generate connection ID for WebSocket
        connection_id = f"conn_{user_id}_{int(asyncio.get_event_loop().time())}"
        
        # Try to join or create room
        room_id = await room_manager.add_user(user_id, connection_id, user_language)
        
        user = room_manager.get_user(user_id)
        room = room_manager.get_user_room(user_id)
        
        response = {
            "user_id": user_id,
            "connection_id": connection_id,
            "language": user_language.value,
            "status": "waiting" if not room_id else "matched",
        }
        
        if room_id:
            partner = room_manager.get_translation_partner(user_id)
            response.update({
                "room_id": room_id,
                "partner_id": partner.user_id if partner else None,
                "partner_language": partner.preferred_language.value if partner else None,
                "message": f"Matched! Ready for {user_language.value} ↔ {partner.preferred_language.value if partner else 'unknown'} translation"
            })
        else:
            response.update({
                "message": f"Waiting for a partner who speaks a different language...",
                "waiting_stats": room_manager.get_waiting_stats()
            })
        
        logger.info(f"User {user_id} joined with language {user_language.value}, status: {response['status']}")
        return response
        
    except Exception as e:
        logger.error(f"Error joining room: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bidirectional-offer")
async def bidirectional_offer(request: dict, background_tasks: BackgroundTasks):
    """Create bidirectional WebRTC connection for matched users"""
    try:
        user_id = request.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")
        
        user = room_manager.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        room = room_manager.get_user_room(user_id)
        if not room or not room.is_ready:
            raise HTTPException(status_code=400, detail="Room not ready for bidirectional translation")
        
        pc_id = request.get("pc_id")
        
        if pc_id and pc_id in pcs_map:
            pipecat_connection = pcs_map[pc_id]
            logger.info(f"Reusing existing bidirectional connection for user {user_id}")
            await pipecat_connection.renegotiate(sdp=request["sdp"], type=request["type"])
        else:
            pipecat_connection = SmallWebRTCConnection(ice_servers)
            await pipecat_connection.initialize(sdp=request["sdp"], type=request["type"])

            @pipecat_connection.event_handler("closed")
            async def handle_disconnected(webrtc_connection: SmallWebRTCConnection):
                logger.info(f"Discarding bidirectional connection for user {user_id}")
                pcs_map.pop(webrtc_connection.pc_id, None)
                # Clean up user from room
                await room_manager.remove_user(user_id)

            # Launch bidirectional bot for this user
            background_tasks.add_task(
                run_bidirectional_bot, 
                pipecat_connection, 
                user_id, 
                user.preferred_language
            )

        answer = pipecat_connection.get_answer()
        pcs_map[answer["pc_id"]] = pipecat_connection

        logger.info(f"Created bidirectional connection for user {user_id} in room {room.room_id}")
        return answer
        
    except Exception as e:
        logger.error(f"Error creating bidirectional offer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/{connection_id}")
async def websocket_endpoint(websocket: WebSocket, connection_id: str):
    """WebSocket endpoint for real-time communication"""
    try:
        await ws_manager.connect(connection_id, websocket)
        logger.info(f"WebSocket connected: {connection_id}")
        
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()
            # Echo back for keep-alive
            await websocket.send_json({
                "type": "ping_response", 
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            })
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
        ws_manager.disconnect(connection_id)
        
        # Find and remove user associated with this connection
        for user_id, user in room_manager.users.items():
            if user.connection_id == connection_id:
                await room_manager.remove_user(user_id)
                logger.info(f"Cleaned up user {user_id} after WebSocket disconnect")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
        ws_manager.disconnect(connection_id)

@app.get("/api/room-stats")
async def get_room_stats():
    """Get statistics about active rooms and waiting users"""
    return {
        "active_rooms": room_manager.get_active_rooms_count(),
        "waiting_users": room_manager.get_waiting_stats(),
        "total_users": len(room_manager.users)
    }

@app.delete("/api/leave-room/{user_id}")
async def leave_room(user_id: str):
    """Leave translation room"""
    try:
        room_id = await room_manager.remove_user(user_id)
        return {
            "user_id": user_id,
            "room_id": room_id,
            "message": "Left room successfully"
        }
    except Exception as e:
        logger.error(f"Error leaving room: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
