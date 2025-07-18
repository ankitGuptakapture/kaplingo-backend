import asyncio
import websockets

async def connect_to_socket():
    uri = "ws://localhost:8080"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to the WebSocket server")

            # Example: Send a message
            await websocket.send("Hello server!")

            # Example: Receive a response
            response = await websocket.recv()
            print("Received from server:", response)

    except Exception as e:
        print("Connection failed:", e)
