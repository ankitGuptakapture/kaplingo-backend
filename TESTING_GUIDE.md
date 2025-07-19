# 🧪 Bidirectional Translation System - Testing Guide

This guide will walk you through testing the bidirectional real-time voice translation system step by step.

## 🚀 Quick Setup & Test

### 1. Prerequisites
```bash
# Ensure you have all dependencies
pip install -r requirements.txt

# Make sure you have a valid Gemini API key in .env
echo "GEMINI_API_KEY=your_api_key_here" > .env
```

### 2. Start the Server
```bash
python main.py
```

You should see:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000
```

## 🔄 Testing Bidirectional Flow

### Method 1: Two Browser Tabs (Single Computer)

1. **Open First Tab (User A)**
   ```
   http://localhost:8000/bidirectional.html
   ```
   - Select **English** from dropdown
   - Click **"Join Room"**
   - You should see: "Waiting for partner..."

2. **Open Second Tab (User B)**
   ```
   http://localhost:8000/bidirectional.html
   ```
   - Select **Hindi** from dropdown  
   - Click **"Join Room"**
   - Both tabs should now show: "Partner found!"

3. **Connect Both Users**
   - In **Tab A**: Click **"Connect"** → Allow microphone access
   - In **Tab B**: Click **"Connect"** → Allow microphone access
   - Both should show: "Translation active!"

4. **Test Translation Flow**
   - **User A** speaks English: "Hello, how are you?"
   - **User A** should hear Hindi translation in their speakers
   - **User B** should see the original English text in their partner panel
   - **User B** speaks Hindi: "मैं ठीक हूँ, धन्यवाद"
   - **User B** should hear English translation in their speakers
   - **User A** should see the original Hindi text in their partner panel

### Method 2: Two Different Devices

1. **Device 1 (Computer/Phone)**
   ```
   http://[your-ip]:8000/bidirectional.html
   ```
   - Select your language (e.g., English)
   - Join room and connect

2. **Device 2 (Another Computer/Phone)**
   ```
   http://[your-ip]:8000/bidirectional.html
   ```
   - Select different language (e.g., Spanish)
   - Join room and connect

3. **Test Cross-Device Translation**
   - Speak on Device 1 → Hear translation on Device 1
   - Speak on Device 2 → Hear translation on Device 2
   - Text coordination visible on both devices

## 🔍 What to Observe

### ✅ Expected Behavior

#### **WebRTC Audio Flow:**
- **User speaks** → **Microphone captures** → **WebRTC sends to bot**
- **Bot processes** → **Translation generated** → **WebRTC sends back to same user**
- **User hears translation** in their own speakers/headphones

#### **WebSocket Coordination:**
- **Original speech text** appears in user's own conversation panel
- **Partner's original speech** appears in partner panel (via WebSocket)
- **Translation text** shows what you said translated
- **Room statistics** update in real-time

#### **Visual Indicators:**
- 🟢 **Green connection indicators** when connected
- 🎵 **Audio visualizers** pulse during speech
- 📝 **Real-time messages** in conversation panels
- 📊 **Live statistics** at bottom

### ❌ Troubleshooting

#### **"Waiting for partner..." forever**
```bash
# Check server logs for errors
tail -f server.log

# Verify room stats
curl http://localhost:8000/api/room-stats
```

#### **WebRTC connection fails**
- **Allow microphone access** in browser
- **Check HTTPS/localhost** - WebRTC requires secure context
- **Try different browser** (Chrome/Firefox work best)

#### **No audio heard**
- **Check browser audio settings**
- **Verify microphone permissions**
- **Test with headphones** to avoid feedback loops

#### **Translations not working**
- **Verify Gemini API key** in `.env` file
- **Check server logs** for API errors
- **Test internet connection**

## 🛠️ Advanced Testing

### Test Different Language Pairs

```bash
# Test various combinations:
# English ↔ Hindi
# English ↔ Spanish  
# Spanish ↔ French
# Hindi ↔ English
# Auto-detect ↔ Any language
```

### Load Testing
```bash
# Open multiple tabs with different language pairs
# Monitor system resources
# Check /api/room-stats for concurrent users
```

### Network Testing
```bash
# Test on different networks
# Test with mobile hotspot
# Test with slower connections
```

## 📊 Monitoring & Debugging

### 1. Server Logs
```bash
# Watch real-time logs
python main.py | grep -E "(User|Translation|WebRTC|Room)"
```

### 2. Browser Developer Tools
```javascript
// Open Console and watch for:
console.log("WebSocket message:", data);
console.log("WebRTC connection state:", peerConnection.connectionState);
console.log("Audio context state:", audioContext.state);
```

### 3. System Statistics
```bash
# Check active rooms and users
curl http://localhost:8000/api/room-stats

# Response should show:
{
  "active_rooms": 1,
  "waiting_users": {"en": 0, "hi": 0},
  "total_users": 2
}
```

### 4. WebSocket Messages
Open browser dev tools → Network → WS → Watch messages:
```json
// Bot-to-bot coordination
{"type": "bot_transcription", "original_text": "Hello"}
{"type": "bot_translation", "translated_text": "नमस्ते"}

// User status updates  
{"type": "user_speech", "text": "Hello", "language": "en"}
{"type": "translation_generated", "translated_text": "नमस्ते"}
```

## 🎯 Success Criteria

### ✅ Complete Flow Working When:

1. **Room Matching:** Users with different languages get paired automatically
2. **WebRTC Audio:** Each user hears their own speech translated in real-time
3. **WebSocket Coordination:** Partners can see each other's original text
4. **Language Detection:** System correctly identifies and translates between languages
5. **Real-time Performance:** Sub-2 second translation latency
6. **Connection Management:** Graceful handling of disconnections
7. **Multi-language Support:** Works with all 8+ supported languages

## 🧪 Test Scenarios

### Scenario 1: Basic English ↔ Hindi
1. User A (English) says: "What's your name?"
2. User A hears: "आपका नाम क्या है?"
3. User B sees: "What's your name?" (original)
4. User B (Hindi) says: "मेरा नाम राज है"
5. User B hears: "My name is Raj"
6. User A sees: "मेरा नाम राज है" (original)

### Scenario 2: Multi-language Chain
1. Test English → Spanish
2. Test Spanish → French  
3. Test French → English
4. Verify all combinations work

### Scenario 3: Edge Cases
1. **Very short phrases:** "Yes", "No", "OK"
2. **Background noise:** Test with music/noise
3. **Rapid speech:** Fast talking
4. **Quiet speech:** Whispered words
5. **Technical terms:** Complex vocabulary

## 📱 Mobile Testing

### iOS Safari / Android Chrome
1. Enable microphone permissions
2. Test WebRTC compatibility
3. Verify WebSocket connections
4. Check audio playback quality

## 🔧 Performance Testing

### Latency Measurement
```javascript
// Add to browser console to measure translation latency
let speechStart = Date.now();
// Speak into microphone
// When you hear translation:
let latency = Date.now() - speechStart;
console.log(`Translation latency: ${latency}ms`);
```

### Resource Monitoring
```bash
# Monitor server resources
htop
# Watch memory usage of Python process
# Monitor CPU usage during active translations
```

---

## 🎉 Expected Results

When everything works correctly:

1. **Instant room matching** between different language users
2. **Real-time translation** with <2 second latency
3. **Clear audio output** in target language
4. **Text coordination** showing original messages
5. **Graceful error handling** for connection issues
6. **Multi-user support** with concurrent translation rooms

The system should feel like **magic** - users speaking different languages can have natural conversations as if they shared the same language! 🌍✨
