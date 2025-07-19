# 🔄 Bidirectional Real-Time Voice Translation System

A sophisticated real-time voice translation system that enables seamless communication between users speaking different languages through WebRTC and AI-powered translation.

## 🌟 Architecture Overview

This system implements a **bidirectional real-time voice translation architecture** where:

- **User1** speaks in their language → **Bot Instance A** transcribes and translates → **User2** hears translation
- **User2** responds in their language → **Bot Instance B** transcribes and translates → **User1** hears translation

### 🔁 Communication Flow

```
User1 ←→ WebRTC ←→ BotA ←→ WebSocket ←→ BotB ←→ WebRTC ←→ User2
```

1. **User1** speaks English → **WebRTC** → **PipecatBotA** transcribes using Gemini
2. **BotA** translates to Hindi and synthesizes speech → **WebRTC** → **User1** hears translation
3. **BotA** sends translation text to **BotB** via **WebSocket** (bot-to-bot coordination)
4. **User2** responds in Hindi → **WebRTC** → **PipecatBotB** processes
5. **BotB** translates to English → **WebRTC** → **User2** hears translation  
6. **BotB** sends translation text to **BotA** via **WebSocket**

## 🏗️ System Components

### Core Files

#### 1. `room_manager.py`
- **User matching and room management**
- Automatic pairing of users with different languages
- Room lifecycle management (waiting → active → closed)
- Support for 8+ languages with smart matching
- Real-time status tracking and cleanup

#### 2. `bidirectional_bot.py`
- **Enhanced Pipecat bot for bidirectional translation**
- Language-specific voice synthesis (Puck, Kalpana, etc.)
- Real-time audio streaming with volume detection
- Partner communication via WebSocket coordination
- Translation cooldown and spam prevention

#### 3. `main.py` (Enhanced)
- **New API endpoints for bidirectional system**
- `POST /api/join-room` - Join or create translation room
- `POST /api/bidirectional-offer` - WebRTC connection for matched users
- `WebSocket /ws/{connection_id}` - Real-time communication
- `GET /api/room-stats` - System statistics
- **Legacy endpoints maintained for backward compatibility**

#### 4. `bidirectional.html`
- **Modern web interface for bidirectional translation**
- Split-panel design showing both users
- Real-time status indicators and audio visualizers
- Language selection with 8+ supported languages
- Live conversation history and translation logs

#### 5. `web_socket.py` (Existing)
- **Enhanced WebSocket manager with audio support**
- Targeted messaging to specific connections
- Base64 audio streaming capabilities
- Connection lifecycle management

## 🌍 Supported Languages

- 🇺🇸 **English** (en) - Voice: Puck
- 🇮🇳 **Hindi** (hi) - Voice: Kalpana  
- 🇪🇸 **Spanish** (es) - Voice: Esperanza
- 🇫🇷 **French** (fr) - Voice: Amelie
- 🇩🇪 **German** (de)
- 🇨🇳 **Chinese** (zh)
- 🇯🇵 **Japanese** (ja)
- 🇸🇦 **Arabic** (ar)
- 🔍 **Auto-detect** (auto)

## 🚀 Quick Start

### 1. Start the Server
```bash
python main.py
```

### 2. Access Bidirectional Interface
```
http://localhost:8000/bidirectional.html
```

### 3. Usage Flow
1. **Select your language** from the dropdown
2. **Click "Join Room"** to find a translation partner
3. **Wait for matching** with someone speaking a different language
4. **Click "Connect"** when partner is found
5. **Start speaking** - translations happen in real-time!

## 🔧 API Endpoints

### Bidirectional Translation

#### Join Room
```http
POST /api/join-room
Content-Type: application/json

{
  "user_id": "optional_user_id",
  "language": "en"
}
```

**Response:**
```json
{
  "user_id": "user_12345",
  "connection_id": "conn_user_12345_1642434567",
  "language": "en",
  "status": "matched",
  "room_id": "room_1642434567_1",
  "partner_id": "user_67890",
  "partner_language": "hi",
  "message": "Matched! Ready for en ↔ hi translation"
}
```

#### Create WebRTC Connection
```http
POST /api/bidirectional-offer
Content-Type: application/json

{
  "user_id": "user_12345",
  "sdp": "webrtc_offer_sdp",
  "type": "offer"
}
```

#### WebSocket Messages
```javascript
// Connect to WebSocket
ws://localhost:8000/ws/{connection_id}

// Message types received:
{
  "type": "partner_speech",           // Partner's original speech
  "type": "translation_text",         // Translation for you
  "type": "audio",                    // Real-time audio stream
  "type": "partner_ready",            // Partner connected
  "type": "partner_disconnected"      // Partner left
}
```

### System Stats
```http
GET /api/room-stats
```

```json
{
  "active_rooms": 5,
  "waiting_users": {
    "en": 2,
    "hi": 1,
    "es": 3
  },
  "total_users": 12
}
```

## 🎯 Key Features

### 🔄 **Real-Time Bidirectional Translation**
- Live voice-to-voice translation between any language pair
- Sub-second latency with WebRTC audio streaming
- Natural conversation flow without interruptions

### 🤖 **AI-Powered Processing**
- Google Gemini Multimodal Live API for transcription
- Context-aware translation with conversational tone
- Language-specific voice synthesis for natural output

### 🏠 **Smart Room Management**
- Automatic matching of users with different languages
- Graceful handling of disconnections and reconnections
- Support for multiple concurrent translation sessions

### 🎵 **Advanced Audio Processing**
- Voice Activity Detection (VAD) for automatic speech recognition
- Real-time audio streaming with intelligent filtering
- Volume-based silence detection and audio optimization

### 🌐 **Modern Web Interface**
- Responsive design that works on desktop and mobile
- Real-time status indicators and connection monitoring
- Live conversation history with message threading
- Audio visualizers showing speaking activity

### 📊 **System Monitoring**
- Real-time statistics on active rooms and users
- Connection health monitoring
- Translation count tracking

## 🔧 Technical Architecture

### WebRTC Audio Pipeline
```
User Microphone → WebRTC → Pipecat Transport → 
Gemini LLM → Translation Processor → 
WebRTC → User Hears Translation
```

### Bot-to-Bot Coordination
```
BotA Transcription → WebSocket → BotB
BotB Translation → WebSocket → BotA Status
Room Management → WebSocket → Both Bots
```

### Complete Message Flow
```
User1 Speech → WebRTC → BotA → Translation → WebRTC → User1 Hears
                            ↓
                       WebSocket (text coordination)
                            ↓
User2 Speech → WebRTC → BotB → Translation → WebRTC → User2 Hears
```

## 🛡️ Error Handling

- **Connection failures**: Automatic cleanup and room management
- **Audio processing errors**: Graceful degradation with text fallback
- **Translation errors**: Retry logic with error notifications
- **WebSocket disconnections**: Partner notification and room cleanup

## 🔮 Advanced Configuration

### Custom Voice Models
```python
LANGUAGE_INSTRUCTIONS = {
    UserLanguage.ENGLISH: {
        "voice_id": "Puck",  # Customize voice
        "target_instructions": {
            # Custom translation instructions
        }
    }
}
```

### Audio Quality Settings
```python
audio_config = {
    "echoCancellation": True,
    "noiseSuppression": True, 
    "autoGainControl": True,
    "sampleRate": 16000
}
```

## 📈 Scalability

- **Horizontal scaling**: Multiple server instances with load balancing
- **Room isolation**: Each translation session is independent
- **Resource optimization**: Automatic cleanup of inactive connections
- **WebSocket pooling**: Efficient connection management

## 🤝 Legacy Compatibility

The system maintains full backward compatibility:
- Original `bot.py` and `/api/offer` endpoint still work
- Existing `index.html` interface remains functional
- New bidirectional features are additive, not replacing

---

## 🎉 Experience

This system creates a **universal translator** experience where:

- **No language barriers** - Anyone can talk to anyone
- **Natural conversations** - Real-time flow without artificial delays  
- **Global connectivity** - Connect people worldwide through language
- **Professional quality** - Enterprise-grade WebRTC and AI technology

Perfect for international meetings, language learning, customer support, or connecting with people worldwide! 🌍
