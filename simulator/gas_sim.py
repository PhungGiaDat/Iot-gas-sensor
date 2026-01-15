"""
IoT Gas Monitoring System - Hardware Simulator

This script simulates an ESP32 gas sensor by publishing
random gas concentration values to HiveMQ Cloud via MQTT (SSL).

When real hardware arrives, replace this script with the ESP32 firmware.
The ESP32 should publish to the same topic with the same JSON format.
"""

import json
import os
import random
import signal
import ssl
import sys
import time

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# =============================================================================
# Load Environment Variables
# =============================================================================

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "iot/sensor/gas")

# Simulation parameters
MIN_GAS_VALUE = 300   # ppm
MAX_GAS_VALUE = 2500  # ppm (to test all levels)
PUBLISH_INTERVAL = 2  # seconds

# Vietnamese safety thresholds
THRESHOLD_WARNING = 500
THRESHOLD_DANGER = 900
THRESHOLD_CRITICAL = 2000

# =============================================================================
# MQTT Callbacks
# =============================================================================

def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker."""
    if rc == 0:
        broker = MQTT_HOST or "broker.hivemq.com"
        print(f"[MQTT] Connected to {broker}:{MQTT_PORT}")
        print(f"[MQTT] Publishing to topic: {MQTT_TOPIC}")
        print(f"[SIM] Gas range: {MIN_GAS_VALUE}-{MAX_GAS_VALUE} ppm")
        print(f"[SIM] Alert threshold: {ALERT_THRESHOLD} ppm")
        print(f"[SIM] Interval: {PUBLISH_INTERVAL} seconds")
        print("-" * 50)
    else:
        print(f"[MQTT] Connection failed with code: {rc}")


def on_disconnect(client, userdata, rc):
    """Callback when disconnected from MQTT broker."""
    print("[MQTT] Disconnected from broker")


def on_publish(client, userdata, mid):
    """Callback when message is published."""
    pass  # Successful publish is logged in main loop

# =============================================================================
# Simulator Logic
# =============================================================================

class GasSensorSimulator:
    """
    Simulates a gas sensor by generating random PPM values.
    
    This mimics the behavior of an MQ-2 or similar gas sensor
    that would be connected to an ESP32 in production.
    """
    
    def __init__(self):
        self.running = True
        self.client = mqtt.Client(client_id="gas_simulator")
        
        # Register callbacks
        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_publish = on_publish
        
        # Configure SSL/TLS for HiveMQ Cloud
        if MQTT_HOST:
            self.client.tls_set(tls_version=ssl.PROTOCOL_TLS)
            self.client.tls_insecure_set(False)
        
        # Set credentials
        if MQTT_USER and MQTT_PASS:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        
        # Setup graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print("\n[SIM] Shutting down...")
        self.running = False
    
    def generate_gas_value(self) -> int:
        """
        Generate a random gas concentration value.
        
        Returns:
            Random integer between MIN_GAS_VALUE and MAX_GAS_VALUE
        """
        return random.randint(MIN_GAS_VALUE, MAX_GAS_VALUE)
    
    def run(self):
        """Main simulation loop."""
        print("=" * 50)
        print("  IoT Gas Sensor Simulator")
        print("  HiveMQ Cloud Edition (SSL/TLS)")
        print("  Press Ctrl+C to stop")
        print("=" * 50)
        
        broker = MQTT_HOST or "broker.hivemq.com"
        port = MQTT_PORT
        
        try:
            # Connect to MQTT broker
            print(f"[MQTT] Connecting to {broker}:{port}...")
            self.client.connect(broker, port, keepalive=60)
            self.client.loop_start()
            
            # Wait for connection
            time.sleep(2)
            
            # Main publishing loop
            reading_count = 0
            while self.running:
                # Generate sensor reading
                gas_value = self.generate_gas_value()
                reading_count += 1
                
                # Create message payload (same format ESP32 will use)
                payload = json.dumps({"value": gas_value})
                
                # Publish to MQTT
                result = self.client.publish(MQTT_TOPIC, payload, qos=0)
                
                # Log the reading with level indicator
                if gas_value > THRESHOLD_CRITICAL:
                    level = "🔴 EXTREMELY DANGEROUS!"
                elif gas_value > THRESHOLD_DANGER:
                    level = "🟠 DANGER!"
                elif gas_value > THRESHOLD_WARNING:
                    level = "🟡 Warning"
                else:
                    level = "🟢 Safe"
                print(f"[{reading_count:04d}] Published: {gas_value} ppm {level}")
                
                # Wait for next reading
                time.sleep(PUBLISH_INTERVAL)
        
        except KeyboardInterrupt:
            print("\n[SIM] Interrupted by user")
        
        except Exception as e:
            print(f"[ERROR] {e}")
        
        finally:
            # Cleanup
            self.client.loop_stop()
            self.client.disconnect()
            print("[SIM] Simulator stopped")

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Check for credentials
    if not MQTT_HOST:
        print("[WARNING] MQTT_HOST not set. Using public broker.hivemq.com (no SSL)")
        print("[WARNING] Set MQTT_HOST in .env for HiveMQ Cloud")
        print("-" * 50)
    
    simulator = GasSensorSimulator()
    simulator.run()
