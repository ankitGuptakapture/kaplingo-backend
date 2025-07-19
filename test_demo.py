#!/usr/bin/env python3
"""
Demo script to test the bidirectional translation system
"""

import asyncio
import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"

def print_status(message, status="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {status}: {message}")

def test_server_health():
    """Test if server is running"""
    try:
        response = requests.get(f"{BASE_URL}/api/room-stats")
        if response.status_code == 200:
            stats = response.json()
            print_status(f"✅ Server is running")
            print_status(f"📊 Current stats: {stats}")
            return True
        else:
            print_status(f"❌ Server responded with status {response.status_code}", "ERROR")
            return False
    except requests.exceptions.ConnectionError:
        print_status("❌ Cannot connect to server. Is it running on port 8000?", "ERROR")
        return False

def test_room_joining():
    """Test room joining functionality"""
    print_status("🏠 Testing room joining...")
    
    # Test User A joining
    user_a_data = {
        "user_id": "test_user_a",
        "language": "en"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/join-room", 
                               json=user_a_data,
                               headers={"Content-Type": "application/json"})
        
        if response.status_code == 200:
            result_a = response.json()
            print_status(f"✅ User A joined: {result_a['user_id']} ({result_a['language']})")
            print_status(f"🔄 Status: {result_a['status']}")
            
            if result_a['status'] == 'waiting':
                print_status("⏳ User A is waiting for partner...")
                
                # Test User B joining
                user_b_data = {
                    "user_id": "test_user_b", 
                    "language": "hi"
                }
                
                response_b = requests.post(f"{BASE_URL}/api/join-room",
                                         json=user_b_data,
                                         headers={"Content-Type": "application/json"})
                
                if response_b.status_code == 200:
                    result_b = response_b.json()
                    print_status(f"✅ User B joined: {result_b['user_id']} ({result_b['language']})")
                    
                    if result_b['status'] == 'matched':
                        print_status(f"🎉 MATCHED! Room: {result_b['room_id']}")
                        print_status(f"👥 Partner: {result_b['partner_id']} ({result_b['partner_language']})")
                        return result_a, result_b
                    else:
                        print_status(f"⚠️ Expected 'matched' but got '{result_b['status']}'", "WARN")
                else:
                    print_status(f"❌ User B join failed: {response_b.status_code}", "ERROR")
            else:
                print_status(f"⚠️ Expected 'waiting' but got '{result_a['status']}'", "WARN")
        else:
            print_status(f"❌ User A join failed: {response.status_code}", "ERROR")
            
    except Exception as e:
        print_status(f"❌ Room joining test failed: {e}", "ERROR")
    
    return None, None

def test_room_cleanup():
    """Test leaving rooms"""
    print_status("🧹 Testing room cleanup...")
    
    try:
        # Try to leave test users
        for user_id in ["test_user_a", "test_user_b"]:
            response = requests.delete(f"{BASE_URL}/api/leave-room/{user_id}")
            if response.status_code == 200:
                print_status(f"✅ Cleaned up {user_id}")
            else:
                print_status(f"⚠️ Could not clean up {user_id} (may not exist)", "WARN")
                
    except Exception as e:
        print_status(f"❌ Cleanup failed: {e}", "ERROR")

def test_api_endpoints():
    """Test all API endpoints"""
    print_status("🔗 Testing API endpoints...")
    
    endpoints = [
        ("GET", "/api/room-stats", None),
        ("GET", "/", None),  # Should return index.html
        ("GET", "/bidirectional.html", None),
    ]
    
    for method, endpoint, data in endpoints:
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}")
            elif method == "POST":
                response = requests.post(f"{BASE_URL}{endpoint}", json=data)
                
            if response.status_code == 200:
                print_status(f"✅ {method} {endpoint}")
            else:
                print_status(f"❌ {method} {endpoint} - Status: {response.status_code}", "ERROR")
                
        except Exception as e:
            print_status(f"❌ {method} {endpoint} - Error: {e}", "ERROR")

def display_manual_test_instructions():
    """Display manual testing instructions"""
    print_status("📋 Manual Testing Instructions:")
    print()
    print("=" * 60)
    print("🌐 BROWSER TESTING")
    print("=" * 60)
    print()
    print("1. Open TWO browser tabs:")
    print(f"   Tab 1: {BASE_URL}/bidirectional.html")
    print(f"   Tab 2: {BASE_URL}/bidirectional.html")
    print()
    print("2. In Tab 1 (User A):")
    print("   - Select 'English' language")
    print("   - Click 'Join Room'")
    print("   - Should show 'Waiting for partner...'")
    print()
    print("3. In Tab 2 (User B):")
    print("   - Select 'Hindi' language") 
    print("   - Click 'Join Room'")
    print("   - Both tabs should show 'Partner found!'")
    print()
    print("4. Connect both users:")
    print("   - Tab 1: Click 'Connect' → Allow microphone")
    print("   - Tab 2: Click 'Connect' → Allow microphone")
    print("   - Both should show 'Translation active!'")
    print()
    print("5. Test bidirectional translation:")
    print("   - User A speaks English: 'Hello, how are you?'")
    print("   - User A should hear Hindi translation")
    print("   - User B should see English text in partner panel")
    print("   - User B speaks Hindi: 'मैं ठीक हूँ, धन्यवाद'")
    print("   - User B should hear English translation")
    print("   - User A should see Hindi text in partner panel")
    print()
    print("=" * 60)
    print("📱 MOBILE/CROSS-DEVICE TESTING")
    print("=" * 60)
    print()
    print("1. Find your local IP address:")
    print("   - Windows: ipconfig")
    print("   - Mac/Linux: ifconfig or ip addr")
    print()
    print("2. Open on Device 1:")
    print("   http://[YOUR-IP]:8000/bidirectional.html")
    print()
    print("3. Open on Device 2:")
    print("   http://[YOUR-IP]:8000/bidirectional.html")
    print()
    print("4. Select different languages and test!")
    print()

def main():
    """Main testing function"""
    print("🚀 Bidirectional Translation System - Test Suite")
    print("=" * 50)
    print()
    
    # Test server health
    if not test_server_health():
        print_status("❌ Server is not running. Please start with: python main.py", "ERROR")
        return
    
    # Clean up any existing test data
    test_room_cleanup()
    time.sleep(1)
    
    # Test API endpoints
    test_api_endpoints()
    time.sleep(1)
    
    # Test room joining
    user_a, user_b = test_room_joining()
    if user_a and user_b:
        print_status("✅ Room joining test PASSED")
    else:
        print_status("❌ Room joining test FAILED", "ERROR")
    
    time.sleep(2)
    
    # Clean up test data
    test_room_cleanup()
    time.sleep(1)
    
    # Final server stats
    print_status("📊 Final server stats:")
    test_server_health()
    print()
    
    # Display manual testing instructions
    display_manual_test_instructions()
    
    print("=" * 60)
    print("✨ NEXT STEPS:")
    print("1. Follow the manual browser testing instructions above")
    print("2. Test with different language combinations")
    print("3. Try cross-device testing")
    print("4. Monitor server logs: python main.py")
    print("5. Check WebSocket messages in browser dev tools")
    print("=" * 60)

if __name__ == "__main__":
    main()
