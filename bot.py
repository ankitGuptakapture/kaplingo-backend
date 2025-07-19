import os
import sys
import asyncio
import time
from dotenv import load_dotenv
from loguru import logger

from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.gemini_multimodal_live.gemini import GeminiMultimodalLiveLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.frames.frames import AudioRawFrame, TranscriptionFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
import numpy as np

load_dotenv(override=True)
from web_socket import ws_manager

SYSTEM_INSTRUCTION = """
You are a simple translator bot. Your only function is to translate between English and Hindi:
1. If the user speaks in English, translate it to Hindi (Devanagari script)
2. If the user speaks in Hindi or any other language, translate it to English
3. Do not answer questions or have conversations
4. Only provide direct translations
5. Keep translations accurate and natural
6. Don't include special characters that might break text streaming
7. Use simple language and avoid complex sentences
8. Speak in a natural and conversational tone
Simply translate what the user said - nothing more, nothing less.

"""

class TranslatorAudioWebSocketStreamer(FrameProcessor):
    """Custom processor to stream translated audio responses to WebSocket clients"""
    
    def __init__(self, volume_threshold: float = 0.01, silence_duration: float = 2.0):
        super().__init__()
        self.is_speaking = False
        self.volume_threshold = volume_threshold
        self.silence_duration = silence_duration
        self.silence_start = None
        self.last_audio_time = 0
        self.tts_active = False
        self.audio_buffer = []
        self.fade_out_frames = 5  # Number of frames to fade out at the end
        self.consecutive_silent_frames = 0
        self.max_silent_frames = 100  # Increased to be less aggressive with silent frame filtering
        
    def _calculate_volume(self, audio_data: bytes) -> float:
        """Calculate RMS volume of audio data"""
        try:
            # Convert bytes to numpy array (assuming 16-bit PCM)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return 0.0
            # Calculate RMS
            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            # Normalize to 0-1 range
            return rms / 32768.0
        except Exception as e:
            logger.error(f"Error calculating volume: {e}")
            return 0.0
    
    def _apply_fade_out(self, audio_data: bytes) -> bytes:
        """Apply fade out to prevent audio jerks"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16).copy()
            if len(audio_array) == 0:
                return audio_data
            
            # Apply fade out to last 15% of the audio
            fade_length = int(len(audio_array) * 0.15)
            if fade_length > 0:
                fade_curve = np.linspace(1.0, 0.0, fade_length)
                audio_array[-fade_length:] = (audio_array[-fade_length:] * fade_curve).astype(np.int16)
            
            return audio_array.tobytes()
        except Exception as e:
            logger.error(f"Error applying fade out: {e}")
            return audio_data
        
    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Capture user's transcriptions (input)
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.UPSTREAM:
            try:
                transcription_data = {
                    "type": "transcription",
                    "text": frame.text,
                    "timestamp": int(time.time() * 1000),
                    "user_id": getattr(frame, 'user_id', 'user')
                }
                await ws_manager.broadcast_json(transcription_data)
                logger.debug(f"Sent user input to WebSocket clients: {frame.text}")
            except Exception as e:
                logger.error(f"Error sending user input to WebSocket: {e}")
        
        # Capture outgoing audio frames (bot's speech) - stream in real-time with improved filtering
        elif isinstance(frame, AudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            try:
                # Only process audio frames when TTS is actively generating speech
                if self.tts_active:
                    # Calculate volume to check if there's actual audio content
                    volume = self._calculate_volume(frame.audio)
                    
                    # Stream audio if there's significant volume OR if we're in the middle of speech
                    if volume > self.volume_threshold:
                        # Reset silent frame counter on speech
                        self.consecutive_silent_frames = 0
                        
                        # Stream audio immediately for real-time playback
                        await ws_manager.broadcast_audio_json(
                            audio_data=frame.audio,
                            sample_rate=frame.sample_rate,
                            format="pcm"
                        )
                        logger.debug(f"Streamed audio frame: {len(frame.audio)} bytes, volume: {volume:.3f}")
                    else:
                        # Handle silent frames during speech
                        self.consecutive_silent_frames += 1
                        
                        # Stream silent frames if we haven't had too many consecutive ones
                        # This helps maintain speech continuity during brief pauses
                        if self.consecutive_silent_frames <= self.max_silent_frames:
                            await ws_manager.broadcast_audio_json(
                                audio_data=frame.audio,
                                sample_rate=frame.sample_rate,
                                format="pcm"
                            )
                            logger.debug(f"Streamed silent frame {self.consecutive_silent_frames}/{self.max_silent_frames}")
                        else:
                            # Skip excessive silent frames
                            logger.debug(f"Skipped excessive silent frame: {self.consecutive_silent_frames}")
                else:
                    # Reset counters when TTS is not active
                    self.consecutive_silent_frames = 0
            except Exception as e:
                logger.error(f"Error processing audio frame: {e}")
        
        # Handle TTS events for Hindi response status
        elif isinstance(frame, TTSStartedFrame):
            self.tts_active = True
            self.is_speaking = True
            logger.info("TTS Started - beginning Hindi audio stream")
            await ws_manager.broadcast_json({
                "type": "speaking_started",
                "timestamp": int(time.time() * 1000)
            })
            await ws_manager.broadcast_json({
                "type": "tts_started",
                "timestamp": int(time.time() * 1000)
            })
            
        elif isinstance(frame, TTSStoppedFrame):
            self.tts_active = False
            self.is_speaking = False
            logger.info("TTS Stopped - ending audio stream") 
            
            await ws_manager.broadcast_json({
                "type": "speaking_stopped",
                "timestamp": int(time.time() * 1000)
            })
            await ws_manager.broadcast_json({
                "type": "tts_stopped",
                "timestamp": int(time.time() * 1000)
            })
        
        # Capture bot's text responses (LLM translations) and send via WebSocket for browser TTS
        elif isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            try:
                # Send the clean LLM translation text to WebSocket clients for browser TTS
                translation_message = {
                    "type": "translation",
                    "text": frame.text,
                    "timestamp": int(time.time() * 1000),
                    "from": "bot_translation"
                }
                await ws_manager.broadcast_json(translation_message)
                logger.info(f"🌐 Sent LLM translation to WebSocket: {frame.text}")
            except Exception as e:
                logger.error(f"Error sending translation text to WebSocket: {e}")

async def run_bot(webrtc_connection):
    pipecat_transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,  # Keep audio output enabled for TTS pipeline
            vad_analyzer=SileroVADAnalyzer(),
            audio_out_10ms_chunks=2,
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
        {"role": "system", "content": "You are a simple translator. If user speaks English, translate to Hindi. If user speaks Hindi or other languages, translate to English. Only provide direct translations, no conversations."},
    ])
    context_aggregator = llm.create_context_aggregator(context)

    # Add the WebSocket translator audio streamer
    translator_audio_streamer = TranslatorAudioWebSocketStreamer()

    pipeline = Pipeline([
        pipecat_transport.input(),
        context_aggregator.user(),
        llm,
        translator_audio_streamer,  # Add the translator audio streamer to capture responses
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
        logger.info("Client connected - Translator ready")
        
        # Notify WebSocket clients about WebRTC connection
        connection_data = {
            "type": "webrtc_connected",
            "client_id": getattr(client, 'id', 'unknown'),
            "timestamp": int(time.time() * 1000),
            "message": "Translator is ready. Speak in English to get Hindi translation, or speak in Hindi to get English translation."
        }
        await ws_manager.broadcast_json(connection_data)
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @pipecat_transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        
        # Notify WebSocket clients about WebRTC disconnection
        disconnection_data = {
            "type": "webrtc_disconnected",
            "client_id": getattr(client, 'id', 'unknown'),
            "timestamp": int(time.time() * 1000)
        }
        await ws_manager.broadcast_json(disconnection_data)
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
