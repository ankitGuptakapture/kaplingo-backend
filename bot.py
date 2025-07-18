import os
import sys
import asyncio
import websockets
import time
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
"You are Gemini Chatbot, a friendly, helpful robot.
Your goal is to demonstrate your capabilities in a succinct way.
Your output will be converted to audio so don't include special characters in your answers.
Respond to what the user said in a creative and helpful way. Keep your responses brief. One or two sentences at most.
"""

class AudioCapture:
    """Captures audio and sends it to WebSocket with debugging"""
    def __init__(self):
        self.websocket = None
        self.connected = False
        self.audio_buffer = bytearray()
        self.last_sent = time.time()
        self.file = open("audio_capture.raw", "wb")  # For debugging

    async def connect(self, uri="ws://localhost:8080"):
        try:
            self.websocket = await websockets.connect(uri)
            self.connected = True
            logger.success(f"Connected to WebSocket at {uri}")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.connected = False

    def add_audio(self, audio_bytes: bytes):
        """Add audio data to buffer and send when ready"""
        if not audio_bytes:
            return
            
        # Save to file for debugging
        self.file.write(audio_bytes)
        self.file.flush()
        
        # Add to buffer
        self.audio_buffer.extend(audio_bytes)
        
        # Send if we have enough data or it's been too long
        current_time = time.time()
        if len(self.audio_buffer) >= 1024 or (current_time - self.last_sent) > 0.1:
            self.send_buffer()

    async def send_buffer(self):
        """Send buffered audio through WebSocket"""
        if not self.connected or not self.websocket or not self.audio_buffer:
            return
            
        try:
            # Send buffered audio
            await self.websocket.send(bytes(self.audio_buffer))
            logger.debug(f"Sent {len(self.audio_buffer)} bytes to WebSocket")

            self.audio_buffer.clear()
            self.last_sent = time.time()
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")
            self.connected = False

    async def close(self):
        """Clean up resources"""
        # Send any remaining audio
        if self.audio_buffer:
            await self.send_buffer()
            
        # Close WebSocket
        if self.websocket and self.connected:
            await self.websocket.close()
            logger.info("WebSocket connection closed")
            
        # Close debug file
        self.file.close()

async def run_bot(webrtc_connection):
    # Create audio capture
    audio_capture = AudioCapture()
    await audio_capture.connect()
    
    # Initialize transport with enhanced audio callback
    def audio_out_callback(audio_bytes: bytes):
        """Handle outgoing audio chunks"""
        if not audio_bytes:
            return
            
        logger.debug(f"Received audio chunk: {len(audio_bytes)} bytes")
        audio_capture.add_audio(audio_bytes)
        
        # Schedule periodic sending
        asyncio.create_task(audio_capture.send_buffer())

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
        logger.info("Client connected - sending greeting")
        await task.queue_frames([context_aggregator.user().get_context_frame()])
        
        # Send test audio to verify WebSocket
        test_audio = b'\x00' * 640  # 20ms of silence
        audio_capture.add_audio(test_audio)
        await audio_capture.send_buffer()

    @pipecat_transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await audio_capture.close()
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)