import os
import sys
import asyncio
import websockets
import time
import json
import threading
import sounddevice as sd
import numpy as np
from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.gemini_multimodal_live import GeminiMultimodalLiveLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport

load_dotenv(override=True)

SYSTEM_INSTRUCTION = """
You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""

class WebSocketServer:
    """WebSocket server to handle audio streaming"""
    def __init__(self, host="localhost", port=8080):
        self.host = host
        self.port = port
        self.clients = set()
        self.server = None
        self.is_running = False
        
    async def handle_client(self, websocket, path):
        """Handle new WebSocket client connections"""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"WebSocket client connected: {client_id}")
        
        self.clients.add(websocket)
        try:
            # Send welcome message
            await websocket.send(json.dumps({
                "type": "welcome",
                "message": "WebSocket server connected successfully",
                "client_id": client_id
            }))
            
            async for message in websocket:
                try:
                    if isinstance(message, bytes):
                        # Handle binary audio data
                        logger.debug(f"Received audio data: {len(message)} bytes from {client_id}")
                        # Here you could process the audio data if needed
                        # For now, we'll just log it
                        
                    else:
                        # Handle JSON messages
                        data = json.loads(message)
                        logger.info(f"Received message from {client_id}: {data}")
                        
                        # Echo back the message
                        await websocket.send(json.dumps({
                            "type": "echo",
                            "original_message": data,
                            "timestamp": time.time()
                        }))
                        
                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON message from {client_id}: {message}")
                except Exception as e:
                    logger.error(f"Error processing message from {client_id}: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket client disconnected: {client_id}")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            self.clients.discard(websocket)
            logger.info(f"Client {client_id} removed from active clients")
    
    async def start_server(self):
        """Start the WebSocket server"""
        try:
            self.server = await websockets.serve(
                self.handle_client,
                self.host,
                self.port,
                ping_interval=20,
                ping_timeout=10
            )
            self.is_running = True
            logger.success(f"WebSocket server started on ws://{self.host}:{self.port}")
            
            # Keep server running
            await self.server.wait_closed()
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            self.is_running = False
    
    async def stop_server(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.is_running = False
            logger.info("WebSocket server stopped")
    
    async def broadcast_message(self, message):
        """Broadcast JSON message to all connected clients"""
        if not self.clients:
            return
            
        disconnected_clients = set()
        for client in self.clients:
            try:
                await client.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                disconnected_clients.add(client)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected_clients.add(client)
        
        # Remove disconnected clients
        self.clients -= disconnected_clients

    async def broadcast_audio(self, audio_bytes):
        """Broadcast binary audio data to all connected clients"""
        if not self.clients:
            logger.debug("No WebSocket clients connected - skipping audio broadcast")
            return
            
        disconnected_clients = set()
        for client in self.clients:
            try:
                await client.send(audio_bytes)
                logger.debug(f"📡 Sent {len(audio_bytes)} bytes of audio to client")
            except websockets.exceptions.ConnectionClosed:
                disconnected_clients.add(client)
            except Exception as e:
                logger.error(f"Error broadcasting audio to client: {e}")
                disconnected_clients.add(client)
        
        # Remove disconnected clients
        self.clients -= disconnected_clients
        
        if disconnected_clients:
            logger.info(f"Removed {len(disconnected_clients)} disconnected clients")


class IndependentMicrophoneCapture:
    """Independent microphone capture using sounddevice - completely separate from pipecat"""
    def __init__(self, audio_capture):
        self.audio_capture = audio_capture
        self.is_recording = False
        self.stream = None
        self.loop = None
        
        # Audio settings
        self.CHUNK = 1024  # Number of frames per buffer
        self.CHANNELS = 1  # Mono audio
        self.RATE = 16000  # Sample rate (16kHz to match WebRTC)
        self.DTYPE = np.int16  # 16-bit resolution

    def start_recording(self):
        """Start independent microphone recording"""
        if self.is_recording:
            return
            
        try:
            logger.info("🎤 Starting independent microphone capture...")
            
            # Store the current event loop for thread-safe communication
            self.loop = asyncio.get_running_loop()
            
            # Start audio stream with callback
            self.stream = sd.InputStream(
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=self.CHUNK,
                callback=self._audio_callback
            )
            
            self.stream.start()
            self.is_recording = True
            logger.success("✅ Independent microphone capture started!")
            
        except Exception as e:
            logger.error(f"❌ Failed to start microphone capture: {e}")

    def _audio_callback(self, indata, frames, time, status):
        """Callback function for audio stream - runs in separate thread"""
        if status:
            logger.warning(f"Audio callback status: {status}")
            
        if indata is not None and self.loop:
            # Convert numpy array to bytes
            audio_bytes = indata.tobytes()
            logger.success(f"🎤 CAPTURED MICROPHONE AUDIO: {len(audio_bytes)} bytes - sending to WebSocket")
            
            # Use thread-safe method to schedule coroutine in the main event loop
            asyncio.run_coroutine_threadsafe(
                self.audio_capture.send_audio_immediately(audio_bytes),
                self.loop
            )

    def stop_recording(self):
        """Stop microphone recording"""
        if not self.is_recording:
            return
            
        logger.info("🎤 Stopping independent microphone capture...")
        
        if self.stream:
            self.stream.stop()
            self.stream.close()
            
        self.is_recording = False
        self.loop = None
        logger.info("✅ Independent microphone capture stopped")

    def cleanup(self):
        """Clean up audio resources"""
        self.stop_recording()

class AudioCapture:
    """Captures audio and sends it to WebSocket with proper error handling"""
    def __init__(self, websocket_server):
        self.websocket_server = websocket_server
        self.websocket = None
        self.connected = False
        self.audio_buffer = bytearray()
        self.last_sent = time.time()
        self.file = open("audio_capture.raw", "wb")
        self.send_lock = asyncio.Lock()
        self.connection_retry_count = 0
        self.max_retries = 3

    async def connect(self, uri="ws://localhost:8080"):
        """Connect to WebSocket server with retry logic"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Attempting WebSocket connection to {uri} (attempt {attempt + 1}/{self.max_retries})")
                
                # Wait a bit for server to be ready
                await asyncio.sleep(1)
                
                self.websocket = await websockets.connect(
                    uri,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                )
                self.connected = True
                logger.success(f"✅ WebSocket connected successfully to {uri}")
                
                # Send initial connection test
                await self.websocket.send(json.dumps({
                    "type": "audio_client_connected",
                    "message": "Audio capture client connected"
                }))
                
                # Start listening for messages
                asyncio.create_task(self._listen_for_messages())
                return True
                
            except ConnectionRefusedError:
                logger.warning(f"Connection refused on attempt {attempt + 1} - WebSocket server may not be ready")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    logger.error("❌ All connection attempts failed - WebSocket server not accessible")
                    
            except Exception as e:
                logger.error(f"❌ WebSocket connection failed on attempt {attempt + 1}: {type(e).__name__}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2)
        
        self.connected = False
        return False

    async def _listen_for_messages(self):
        """Listen for messages from the server"""
        try:
            logger.info("🔄 Started listening for WebSocket messages")
            async for message in self.websocket:
                try:
                    if isinstance(message, bytes):
                        logger.debug(f"📨 Received binary message: {len(message)} bytes")
                    else:
                        data = json.loads(message)
                        logger.info(f"📨 Received from server: {data}")
                except json.JSONDecodeError:
                    logger.info(f"📨 Received text message: {message}")
                except Exception as e:
                    logger.error(f"❌ Error processing message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 WebSocket connection closed")
            self.connected = False
        except Exception as e:
            logger.error(f"❌ Error in message listener: {type(e).__name__}: {e}")
            self.connected = False

    def add_audio(self, audio_bytes: bytes):
        """Add audio data to buffer and send immediately for real-time streaming"""
        if not audio_bytes:
            return
            
        # Save to file for debugging
        self.file.write(audio_bytes)
        self.file.flush()
        
        # For real-time streaming, send audio immediately without buffering
        # This ensures every audio chunk is sent as soon as it's received
        logger.debug(f"🎵 Received audio chunk: {len(audio_bytes)} bytes - sending immediately")
        asyncio.create_task(self.send_audio_immediately(audio_bytes))

    async def send_audio_immediately(self, audio_bytes: bytes):
        """Send audio data immediately for real-time streaming"""
        if not audio_bytes:
            logger.debug("Cannot send audio - no audio data")
            return
            
        try:
            # Broadcast audio data to all connected WebSocket clients
            await self.websocket_server.broadcast_audio(audio_bytes)
            logger.success(f"🎵 Broadcasted {len(audio_bytes)} bytes of audio to all WebSocket clients")
            self.last_sent = time.time()
            
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")

    async def send_buffer(self):
        """Send buffered audio through WebSocket"""
        logger.debug("Attempting to send audio buffer")
            
        if not self.connected or not self.websocket or not self.audio_buffer:
            logger.debug("Cannot send - not connected or no audio buffer")
            return
            
        async with self.send_lock:
            if not self.audio_buffer:
                logger.debug("Audio buffer is empty")
                return
                
            try:
                audio_data = bytes(self.audio_buffer)
                logger.success(f"🎵 Sending {len(audio_data)} bytes of audio data to WebSocket")
                
                # Send raw audio bytes to WebSocket
                await self.websocket.send(audio_data)
                logger.success(f"✅ Successfully sent {len(audio_data)} bytes to WebSocket")

                self.audio_buffer.clear()
                self.last_sent = time.time()
                
            except websockets.exceptions.ConnectionClosed:
                logger.error("WebSocket connection closed during send")
                self.connected = False
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
                self.connected = False

    async def send_text_message(self, message: dict):
        """Send a JSON message to the server"""
        if not self.connected or not self.websocket:
            logger.warning("Cannot send message - WebSocket not connected")
            return
            
        try:
            await self.websocket.send(json.dumps(message))
            logger.debug(f"Sent text message: {message}")
        except Exception as e:
            logger.error(f"Error sending text message: {e}")

    async def close(self):
        """Clean up resources"""
        if self.audio_buffer:
            await self.send_buffer()
            
        if self.websocket and self.connected:
            try:
                await self.websocket.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")
            
        self.file.close()

async def run_websocket_server():
    """Run the WebSocket server in the background"""
    server = WebSocketServer()
    await server.start_server()
    return server

async def run_bot(webrtc_connection):
    """Run the main bot with WebRTC and WebSocket integration"""
    
    # Start WebSocket server
    logger.info("Starting WebSocket server...")
    websocket_server = WebSocketServer()
    server_task = asyncio.create_task(websocket_server.start_server())
    
    # Wait a moment for server to start
    await asyncio.sleep(2)
    
    # Create audio capture
    audio_capture = AudioCapture(websocket_server)
    
    # Try to connect to WebSocket server
    connection_success = await audio_capture.connect()
    if not connection_success:
        logger.error("Failed to establish WebSocket connection - continuing without it")
    
    # Create independent microphone capture (completely separate from pipecat)
    mic_capture = IndependentMicrophoneCapture(audio_capture)
    
    # Audio callback for bot output only
    def audio_out_callback(audio_bytes: bytes):
        """Handle outgoing audio chunks (bot's speech)"""
        if not audio_bytes:
            return
            
        logger.debug(f"Received bot output audio chunk: {len(audio_bytes)} bytes")
        
        # Send bot's audio to WebSocket if connected (optional - you may not want bot audio)
        # if audio_capture.connected:
        #     audio_capture.add_audio(audio_bytes)

    # Initialize transport (clean pipeline without interceptors)
    pipecat_transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            audio_out_10ms_chunks=2,
            audio_out_callback=audio_out_callback
        ),
    )

    # Initialize services
    llm = GeminiMultimodalLiveLLMService(
        api_key="AIzaSyDLe4QJ0Wc9fmfeLXrPIkWFlWJvPX7O5IY",
        voice_id="Puck",
        transcribe_user_audio=True,
        transcribe_model_audio=True,
        system_instruction=SYSTEM_INSTRUCTION,
    )

    context = OpenAILLMContext([
        {"role": "user", "content": "Start by greeting the user warmly and introducing yourself."}
    ])
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        pipecat_transport.input(),
        context_aggregator.user(),
        llm,
        pipecat_transport.output(),
        context_aggregator.assistant()
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @pipecat_transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("WebRTC client connected - sending greeting")
        await task.queue_frames([context_aggregator.user().get_context_frame()])
        
        # Start independent microphone capture
        mic_capture.start_recording()
        
        # Notify WebSocket server about WebRTC connection
        await websocket_server.broadcast_message({
            "type": "webrtc_client_connected",
            "message": "WebRTC client connected successfully",
            "timestamp": time.time()
        })
        
        # Send test audio if WebSocket is connected
        if audio_capture.connected:
            test_audio = b'\x00' * 640  # 20ms of silence
            audio_capture.add_audio(test_audio)

    @pipecat_transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("WebRTC client disconnected")
        
        # Stop independent microphone capture
        mic_capture.stop_recording()
        
        # Notify WebSocket server
        await websocket_server.broadcast_message({
            "type": "webrtc_client_disconnected",
            "message": "WebRTC client disconnected",
            "timestamp": time.time()
        })
        
        # Clean up
        await audio_capture.close()
        await websocket_server.stop_server()
        await task.cancel()

    # Run the pipeline
    runner = PipelineRunner(handle_sigint=False)
    
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
    finally:
        # Clean up
        await audio_capture.close()
        await websocket_server.stop_server()

# Test function to verify WebSocket server independently
async def test_websocket_connection():
    """Test WebSocket server independently"""
    logger.info("Testing WebSocket server...")
    
    try:
        # Connect to WebSocket
        websocket = await websockets.connect("ws://localhost:8080")
        logger.success("✅ WebSocket connection test successful!")
        
        # Send test message
        await websocket.send(json.dumps({"type": "test", "message": "Hello WebSocket!"}))
        
        # Receive response
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        logger.info(f"📥 Received: {response}")
        
        await websocket.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ WebSocket test failed: {e}")
        return False

if __name__ == "__main__":
    # Run a quick test
    asyncio.run(test_websocket_connection())
