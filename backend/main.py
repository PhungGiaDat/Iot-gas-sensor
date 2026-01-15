"""
IoT Gas Monitoring System - Backend
FastAPI + HiveMQ Cloud (SSL) + Supabase + WebSocket Bridge

This module provides:
- MQTT subscription to gas sensor data via HiveMQ Cloud (SSL)
- Supabase integration for data persistence
- Alert logic for high gas levels (> 600 ppm)
- WebSocket broadcasting to connected clients
- REST API endpoints for history and alerts
"""

import asyncio
import json
import os
import ssl
from datetime import datetime
from typing import List

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi_mqtt import FastMQTT, MQTTConfig
from supabase import create_client, Client

# Get the frontend directory path
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# =============================================================================
# Load Environment Variables
# =============================================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iot/sensor/gas")

# Device Configuration
DEVICE_ID = "esp32_01"

# Threshold levels (Vietnamese safety standards)
# Level 1: 300-500 (Safe)
# Level 2: 501-900 (Warning) 
# Level 3: 901-2000 (Dangerous - Trigger siren)
# Level 4: >2000 (Extremely Dangerous)
ALERT_THRESHOLD_WARNING = 500   # Level 2 warning
ALERT_THRESHOLD_DANGER = 900    # Level 3 danger (siren trigger)
ALERT_THRESHOLD_CRITICAL = 2000 # Level 4 critical

# =============================================================================
# Application Setup
# =============================================================================

app = FastAPI(
    title="IoT Gas Monitoring System",
    description="Real-time gas concentration monitoring via MQTT and WebSockets",
    version="2.0.0"
)

# CORS configuration for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Supabase Client
# =============================================================================

supabase: Client = None

def init_supabase():
    """Initialize Supabase client with error handling."""
    global supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            print(f"[SUPABASE] Connected to {SUPABASE_URL}")
        except Exception as e:
            print(f"[SUPABASE] Warning: Failed to connect - {e}")
            print("[SUPABASE] Database features disabled. Check your credentials.")
            supabase = None
    else:
        print("[SUPABASE] Warning: Credentials not configured. Database features disabled.")

# Initialize on module load
init_supabase()

# =============================================================================
# MQTT Configuration with SSL
# =============================================================================

# Create SSL context for HiveMQ Cloud
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = True
ssl_context.verify_mode = ssl.CERT_REQUIRED

mqtt_config = MQTTConfig(
    host=MQTT_HOST or "broker.hivemq.com",
    port=MQTT_PORT,
    keepalive=60,
    username=MQTT_USER,
    password=MQTT_PASS,
    ssl=ssl_context if MQTT_HOST else False,  # Only use SSL for HiveMQ Cloud
)

fast_mqtt = FastMQTT(config=mqtt_config)
fast_mqtt.init_app(app)

# =============================================================================
# WebSocket Connection Manager
# =============================================================================

class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts messages to all clients.
    
    This is the bridge between MQTT messages and web clients.
    When ESP32 hardware is connected, it publishes to MQTT,
    and this manager broadcasts to all connected browsers.
    """
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from the registry."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: str):
        """Send a message to all connected WebSocket clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


# Global connection manager instance
manager = ConnectionManager()

# =============================================================================
# Database Operations (Async)
# =============================================================================

async def save_gas_reading(value: int):
    """
    Save gas reading to Supabase asynchronously.
    Uses asyncio.to_thread to avoid blocking the event loop.
    """
    if not supabase:
        return
    
    try:
        def _insert():
            return supabase.table("gas_readings").insert({
                "device_id": DEVICE_ID,
                "value": value
            }).execute()
        
        await asyncio.to_thread(_insert)
        print(f"[DB] Saved reading: {value} ppm")
    except Exception as e:
        print(f"[DB] Error saving reading: {e}")


async def save_alert(value: int, message: str):
    """
    Save alert to Supabase asynchronously.
    Uses asyncio.to_thread to avoid blocking the event loop.
    """
    if not supabase:
        return
    
    try:
        def _insert():
            return supabase.table("alerts").insert({
                "device_id": DEVICE_ID,
                "level": value,
                "message": message
            }).execute()
        
        await asyncio.to_thread(_insert)
        print(f"[DB] Saved alert: {message}")
    except Exception as e:
        print(f"[DB] Error saving alert: {e}")


# =============================================================================
# MQTT Event Handlers
# =============================================================================

@fast_mqtt.on_connect()
def on_connect(client, flags, rc, properties):
    """Callback when connected to MQTT broker."""
    broker = MQTT_HOST or "broker.hivemq.com"
    print(f"[MQTT] Connected to {broker}:{MQTT_PORT}")
    fast_mqtt.client.subscribe(MQTT_TOPIC)
    print(f"[MQTT] Subscribed to topic: {MQTT_TOPIC}")


@fast_mqtt.on_disconnect()
def on_disconnect(client, packet, exc=None):
    """Callback when disconnected from MQTT broker."""
    print("[MQTT] Disconnected from broker")


@fast_mqtt.on_message()
async def on_message(client, topic, payload, qos, properties):
    """
    Callback when message received from MQTT broker.
    
    Parses the gas sensor data, saves to database, and broadcasts to WebSocket clients.
    If value > 600: creates alert and sends prefixed message.
    
    Supports both formats:
    - Raw integer: 523
    - JSON object: {"value": 523}
    """
    try:
        # Decode the incoming message
        raw_data = payload.decode().strip()
        
        # Try to parse as JSON first
        try:
            data = json.loads(raw_data)
            # Handle both {"value": 123} and just 123
            if isinstance(data, dict):
                value = data.get("value", 0)
            elif isinstance(data, (int, float)):
                value = int(data)
            else:
                value = int(data)
        except (json.JSONDecodeError, ValueError):
            # If not valid JSON, try to parse as raw integer
            value = int(raw_data)
        
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        print(f"[MQTT] Received: {value} ppm")
        
        # Save reading to database (non-blocking)
        asyncio.create_task(save_gas_reading(value))
        
        # Determine alert level based on safety standards
        if value > ALERT_THRESHOLD_CRITICAL:
            # Level 4: Extremely Dangerous
            alert_level = "CRITICAL"
            alert_message = "EXTREMELY DANGEROUS! High flammable gas concentration!"
            is_alert = True
        elif value > ALERT_THRESHOLD_DANGER:
            # Level 3: Dangerous (Trigger siren)
            alert_level = "DANGER"
            alert_message = "DANGER! Gas leak detected!"
            is_alert = True
        elif value > ALERT_THRESHOLD_WARNING:
            # Level 2: Warning
            alert_level = "WARNING"
            alert_message = "Light warning - Unusual smell detected"
            is_alert = True
        else:
            # Level 1: Safe
            alert_level = "SAFE"
            is_alert = False
        
        if is_alert:
            # Save alert to database
            asyncio.create_task(save_alert(value, alert_message))
            
            # Broadcast with ALERT prefix
            ws_message = f"ALERT:{json.dumps({'value': value, 'timestamp': timestamp, 'level': alert_level, 'message': alert_message})}"
        else:
            # Normal broadcast
            ws_message = json.dumps({"value": value, "timestamp": timestamp, "level": alert_level})
        
        # Broadcast to all connected WebSocket clients
        await manager.broadcast(ws_message)
        
    except json.JSONDecodeError as e:
        print(f"[MQTT] Invalid JSON received: {e}")
    except Exception as e:
        print(f"[MQTT] Error processing message: {e}")

# =============================================================================
# WebSocket Endpoint
# =============================================================================

@app.websocket("/ws/gas")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time gas data streaming.
    
    Clients connect here to receive live gas concentration updates.
    The frontend Chart.js graph subscribes to this endpoint.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, waiting for client messages (if any)
            # The actual data flow is MQTT -> broadcast, not client -> server
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# =============================================================================
# REST API Endpoints
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend dashboard."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse(content="<h1>Frontend not found. Place index.html in frontend folder.</h1>", status_code=404)


@app.get("/api")
async def api_info():
    """API information endpoint."""
    return {
        "name": "IoT Gas Monitoring System",
        "version": "2.0.0",
        "endpoints": {
            "dashboard": "/",
            "websocket": "/ws/gas",
            "history": "/api/history",
            "alerts": "/api/alerts",
            "status": "/status"
        }
    }


@app.get("/api/history")
async def get_history():
    """
    Get the last 50 gas readings from database.
    
    Returns:
        List of gas readings with device_id, value, and created_at
    """
    if not supabase:
        return JSONResponse(
            status_code=503,
            content={"error": "Database not configured"}
        )
    
    try:
        def _query():
            return supabase.table("gas_readings") \
                .select("*") \
                .order("created_at", desc=True) \
                .limit(50) \
                .execute()
        
        result = await asyncio.to_thread(_query)
        # Reverse to get chronological order for chart
        readings = list(reversed(result.data)) if result.data else []
        return {"data": readings}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/alerts")
async def get_alerts():
    """
    Get the last 10 alerts from database.
    
    Returns:
        List of alerts with device_id, level, message, and created_at
    """
    if not supabase:
        return JSONResponse(
            status_code=503,
            content={"error": "Database not configured"}
        )
    
    try:
        def _query():
            return supabase.table("alerts") \
                .select("*") \
                .order("created_at", desc=True) \
                .limit(10) \
                .execute()
        
        result = await asyncio.to_thread(_query)
        return {"data": result.data or []}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/status")
async def health_status():
    """
    Health check endpoint for system monitoring.
    
    Returns:
        - MQTT connection status
        - Number of connected WebSocket clients
        - Supabase connection status
        - Current timestamp
    """
    try:
        mqtt_connected = fast_mqtt.client.is_connected() if fast_mqtt.client else False
    except Exception:
        mqtt_connected = False
    
    return JSONResponse(
        content={
            "status": "healthy" if mqtt_connected else "degraded",
            "mqtt": {
                "connected": mqtt_connected,
                "broker": MQTT_HOST or "broker.hivemq.com",
                "topic": MQTT_TOPIC
            },
            "websocket": {
                "active_connections": len(manager.active_connections)
            },
            "supabase": {
                "configured": supabase is not None
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
