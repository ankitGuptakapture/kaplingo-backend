import os
import sys
import asyncio
import time
from dotenv import load_dotenv
from loguru import logger
from typing import Optional, Dict, Any

from pipecat.audio.vad.silero import SileroVADAnalyzer
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
from room_manager import room_manager, UserLanguage

# Language-specific system instructions for better translation
LANGUAGE_INSTRUCTIONS = {
    UserLanguage.ENGLISH: {
        "voice_id": "Puck",
        "target_instructions": {
            UserLanguage.HINDI: "Translate the following English text to natural Hindi (Devanagari script). Use conversational, everyday language that sounds natural to native Hindi speakers.",
            UserLanguage.SPANISH: "Translate the following English text to natural Spanish. Use conversational, everyday language.",
            UserLanguage.FRENCH: "Translate the following English text to natural French. Use conversational, everyday language.",
            UserLanguage.GERMAN: "Translate the following English text to natural German. Use conversational, everyday language.",
            UserLanguage.CHINESE: "Translate the following English text to natural Simplified Chinese. Use conversational, everyday language.",
            UserLanguage.JAPANESE: "Translate the following English text to natural Japanese. Use conversational, everyday language.",
            UserLanguage.ARABIC: "Translate the following English text to natural Arabic. Use conversational, everyday language."
        }
    },
    UserLanguage.HINDI: {
        "voice_id": "Kalpana",
        "target_instructions": {
            UserLanguage.ENGLISH: "Translate the following Hindi text to natural English. Use conversational, everyday language.",
            UserLanguage.SPANISH: "Translate the following Hindi text to natural Spanish through English if needed.",
            UserLanguage.FRENCH: "Translate the following Hindi text to natural French through English if needed.",
            UserLanguage.GERMAN: "Translate the following Hindi text to natural German through English if needed.",
            UserLanguage.CHINESE: "Translate the following Hindi text to natural Chinese through English if needed.",
            UserLanguage.JAPANESE: "Translate the following Hindi text to natural Japanese through English if needed.",
            UserLanguage.ARABIC: "Translate the following Hindi text to natural Arabic through English if needed."
        }
    },
    UserLanguage.SPANISH: {
        "voice_id": "Esperanza",
        "target_instructions": {
            UserLanguage.ENGLISH: "Translate the following Spanish text to natural English. Use conversational, everyday language.",
            UserLanguage.HINDI: "Translate the following Spanish text to natural Hindi through English if needed.",
        }
    },
    UserLanguage.FRENCH: {
        "voice_id": "Amelie",
        "target_instructions": {
            UserLanguage.ENGLISH: "Translate the following French text to natural English. Use conversational, everyday language.",
            UserLanguage.HINDI: "Translate the following French text to natural Hindi through English if needed.",
        }
    },
    UserLanguage.AUTO_DETECT: {
        "voice_id": "Puck",
        "target_instructions": {
            UserLanguage.ENGLISH: "Detect the language and translate to natural English. Use conversational, everyday language.",
            UserLanguage.HINDI: "Detect the language and translate to natural Hindi (Devanagari script).",
        }
    }
}

class BidirectionalTranslationProcessor(FrameProcessor):
    """Enhanced processor for bidirectional real-time translation between paired users"""
    
    def __init__(self, user_id: str, user_language: UserLanguage, 
                 volume_threshold: float = 0.01, silence_duration: float = 2.0):
        super().__init__()
        self.user_id = user_id
        self.user_language = user_language
        self.volume_threshold = volume_threshold
        self.silence_duration = silence_duration
        
        self.is_speaking = False
        self.tts_active = False
        self.silence_start = None
        self.last_audio_time = 0
        self.consecutive_silent_frames = 0
        self.max_silent_frames = 50
        
        # Translation state
        self.last_translation_time = 0
        self.translation_cooldown = 1.0  # Minimum seconds between translations
        
    def _calculate_volume(self, audio_data: bytes) -> float:
        """Calculate RMS volume of audio data"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return 0.0
            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            return rms / 32768.0
        except Exception as e:
            logger.error(f"Error calculating volume: {e}")
            return 0.0
    
    def _get_translation_instruction(self, target_language: UserLanguage) -> str:
        """Get appropriate translation instruction based on source and target languages"""
        if self.user_language in LANGUAGE_INSTRUCTIONS:
            target_instructions = LANGUAGE_INSTRUCTIONS[self.user_language]["target_instructions"]
            return target_instructions.get(target_language, 
                f"Translate to {target_language.value}. Use natural, conversational language.")
        return f"Translate to {target_language.value}. Use natural, conversational language."
    
    async def _send_to_partner_bot(self, message_type: str, data: Dict[str, Any]):
        """Send message to partner bot via WebSocket for bot-to-bot communication"""
        try:
            partner = room_manager.get_translation_partner(self.user_id)
            if not partner:
                logger.warning(f"No translation partner found for user {self.user_id}")
                return
            
            # Send bot-to-bot communication message
            bot_message = {
                "type": f"bot_{message_type}",
                "from_user": self.user_id,
                "to_user": partner.user_id,
                "from_language": self.user_language.value,
                "to_language": partner.preferred_language.value,
                "timestamp": int(time.time() * 1000),
                **data
            }
            
            # Use a bot-specific channel for coordination
            await ws_manager.broadcast_json(bot_message)
                
        except Exception as e:
            logger.error(f"Error sending message to partner bot: {e}")

    async def _send_status_to_user(self, message_type: str, data: Dict[str, Any]):
        """Send status messages to user's WebSocket connection"""
        try:
            user = room_manager.get_user(self.user_id)
            if not user:
                return
                
            user_message = {
                "type": message_type,
                "user_id": self.user_id,
                "timestamp": int(time.time() * 1000),
                **data
            }
            
            await ws_manager.send_json(user.connection_id, user_message)
                
        except Exception as e:
            logger.error(f"Error sending status to user: {e}")
    
    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Handle user's speech input (transcription from user's microphone)
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.UPSTREAM:
            await self._handle_user_speech(frame)
            
        # Handle bot's generated audio (translation output)
        elif isinstance(frame, AudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            await self._handle_translation_audio(frame)
            
        # Handle TTS events
        elif isinstance(frame, TTSStartedFrame):
            await self._handle_tts_started()
            
        elif isinstance(frame, TTSStoppedFrame):
            await self._handle_tts_stopped()
            
        # Handle bot's text responses (translations)
        elif isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            await self._handle_translation_text(frame)
    
    async def _handle_user_speech(self, frame: TranscriptionFrame):
        """Handle user's speech input and broadcast to partner"""
        try:
            current_time = time.time()
            
            # Apply translation cooldown to prevent spam
            if current_time - self.last_translation_time < self.translation_cooldown:
                logger.debug(f"Translation cooldown active for user {self.user_id}")
                return
            
            # Update speaking status
            room_manager.set_user_speaking_status(self.user_id, True)
            
            # Send user's transcription to their own connection for feedback
            transcription_data = {
                "type": "user_speech",
                "text": frame.text,
                "user_id": self.user_id,
                "language": self.user_language.value,
                "timestamp": int(time.time() * 1000)
            }
            
            user = room_manager.get_user(self.user_id)
            if user:
                await ws_manager.send_json(user.connection_id, transcription_data)
            
            # Send original speech to partner bot for context via bot-to-bot communication
            await self._send_to_partner_bot("transcription", {
                "original_text": frame.text,
                "original_language": self.user_language.value
            })
            
            self.last_translation_time = current_time
            logger.info(f"👤 User {self.user_id} ({self.user_language.value}): {frame.text}")
            
        except Exception as e:
            logger.error(f"Error handling user speech: {e}")
    
    async def _handle_translation_audio(self, frame: AudioRawFrame):
        """Handle translated audio output - this goes back to the same user via WebRTC"""
        try:
            if not self.tts_active:
                return
                
            # The translated audio goes back to the user via WebRTC pipeline
            # Bot-to-bot coordination happens via WebSocket for text, not audio
            volume = self._calculate_volume(frame.audio)
            
            if volume > self.volume_threshold:
                self.consecutive_silent_frames = 0
                logger.debug(f"🔊 Generated translation audio: {len(frame.audio)} bytes")
            else:
                self.consecutive_silent_frames += 1
                        
        except Exception as e:
            logger.error(f"Error handling translation audio: {e}")
    
    async def _handle_tts_started(self):
        """Handle TTS start event"""
        self.tts_active = True
        self.is_speaking = True
        
        # Send status to user about TTS starting
        await self._send_status_to_user("translation_audio_started", {
            "message": "Translation audio starting"
        })
        
        # Notify partner bot about TTS activity
        await self._send_to_partner_bot("tts_started", {
            "message": "Partner translation audio starting"
        })
        
        logger.info(f"🎵 TTS started for user {self.user_id}")
    
    async def _handle_tts_stopped(self):
        """Handle TTS stop event"""
        self.tts_active = False
        self.is_speaking = False
        
        # Update user speaking status
        room_manager.set_user_speaking_status(self.user_id, False)
        
        # Send status to user about TTS stopping
        await self._send_status_to_user("translation_audio_stopped", {
            "message": "Translation audio finished"
        })
        
        # Notify partner bot about TTS completion
        await self._send_to_partner_bot("tts_stopped", {
            "message": "Partner translation audio finished"
        })
        
        logger.info(f"🎵 TTS stopped for user {self.user_id}")
    
    async def _handle_translation_text(self, frame: TranscriptionFrame):
        """Handle translated text and send to partner via bot-to-bot communication"""
        try:
            partner = room_manager.get_translation_partner(self.user_id)
            if not partner:
                return
                
            # Send translation to partner bot via bot-to-bot communication
            await self._send_to_partner_bot("translation", {
                "translated_text": frame.text,
                "target_language": partner.preferred_language.value
            })
            
            # Send translation to user's WebSocket for their own feedback
            await self._send_status_to_user("translation_generated", {
                "translated_text": frame.text,
                "target_language": partner.preferred_language.value
            })
            
            # Also send to room for logging
            room = room_manager.get_user_room(self.user_id)
            if room:
                await ws_manager.broadcast_json({
                    "type": "room_translation",
                    "room_id": room.room_id,
                    "from_user": self.user_id,
                    "to_user": partner.user_id,
                    "translation": frame.text,
                    "from_language": self.user_language.value,
                    "to_language": partner.preferred_language.value,
                    "timestamp": int(time.time() * 1000)
                })
            
            logger.info(f"🌐 Translation {self.user_id} → {partner.user_id}: {frame.text}")
            
        except Exception as e:
            logger.error(f"Error handling translation text: {e}")

async def run_bidirectional_bot(webrtc_connection, user_id: str, user_language: UserLanguage):
    """Run a bidirectional translation bot for a specific user"""
    
    # Get partner to determine target language
    partner = room_manager.get_translation_partner(user_id)
    target_language = partner.preferred_language if partner else UserLanguage.ENGLISH
    
    # Get language-specific configuration
    lang_config = LANGUAGE_INSTRUCTIONS.get(user_language, LANGUAGE_INSTRUCTIONS[UserLanguage.AUTO_DETECT])
    voice_id = lang_config["voice_id"]
    
    # Build system instruction
    translation_instruction = lang_config["target_instructions"].get(
        target_language,
        f"Translate to {target_language.value}. Use natural, conversational language."
    )
    
    system_instruction = f"""
You are a real-time translation assistant in a bidirectional conversation system.

IMPORTANT RULES:
1. {translation_instruction}
2. ONLY provide the translation - no explanations, no conversations, no extra text
3. Keep translations natural and conversational
4. Preserve the speaker's tone and intent
5. For very short utterances (like "ok", "yes", "no"), translate directly
6. If you hear unclear audio, respond with "[unclear]" in the target language
7. Maintain the same emotional tone as the original speaker
8. Use everyday, spoken language rather than formal written language

Current conversation: User speaks {user_language.value}, translate to {target_language.value}
"""

    # Setup WebRTC transport
    pipecat_transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            audio_out_10ms_chunks=2,
        ),
    )

    # Initialize Gemini LLM service
    llm = GeminiMultimodalLiveLLMService(
        api_key=os.getenv("GEMINI_API_KEY", "AIzaSyDLe4QJ0Wc9fmfeLXrPIkWFlWJvPX7O5IY"),
        voice_id=voice_id,
        transcribe_user_audio=True,
        transcribe_model_audio=True,
        system_instruction=system_instruction,
    )

    # Setup context
    context = OpenAILLMContext([
        {"role": "system", "content": system_instruction},
    ])
    context_aggregator = llm.create_context_aggregator(context)

    # Create bidirectional processor
    translation_processor = BidirectionalTranslationProcessor(
        user_id=user_id,
        user_language=user_language
    )

    # Build pipeline
    pipeline = Pipeline([
        pipecat_transport.input(),
        context_aggregator.user(),
        llm,
        translation_processor,
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
        logger.info(f"🔗 User {user_id} connected for bidirectional translation")
        
        # Notify about successful connection
        user = room_manager.get_user(user_id)
        partner = room_manager.get_translation_partner(user_id)
        room = room_manager.get_user_room(user_id)
        
        if user and partner and room:
            connection_data = {
                "type": "bidirectional_ready",
                "user_id": user_id,
                "partner_id": partner.user_id,
                "room_id": room.room_id,
                "user_language": user_language.value,
                "partner_language": partner.preferred_language.value,
                "message": f"Ready for {user_language.value} ↔ {partner.preferred_language.value} translation",
                "timestamp": int(time.time() * 1000)
            }
            
            # Send to both users
            await ws_manager.send_json(user.connection_id, connection_data)
            await ws_manager.send_json(partner.connection_id, {
                **connection_data,
                "type": "partner_ready",
                "message": f"Your partner is ready for translation"
            })
        
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @pipecat_transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"🔌 User {user_id} disconnected from bidirectional translation")
        
        # Notify partner about disconnection
        partner = room_manager.get_translation_partner(user_id)
        if partner:
            disconnection_data = {
                "type": "partner_disconnected",
                "user_id": user_id,
                "partner_id": partner.user_id,
                "message": "Your translation partner has disconnected",
                "timestamp": int(time.time() * 1000)
            }
            await ws_manager.send_json(partner.connection_id, disconnection_data)
        
        # Clean up room
        await room_manager.remove_user(user_id)
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Error running bidirectional bot for user {user_id}: {e}")
        await room_manager.remove_user(user_id)
        raise
