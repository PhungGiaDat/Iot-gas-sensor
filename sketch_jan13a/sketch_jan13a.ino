#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>

// 1. Cấu hình WiFi
const char* ssid = "Gia Dat";
const char* password = "giadatgiathanh";

// 2. Cấu hình HiveMQ (Lấy từ hình ảnh của bạn)
// - URL
const char* mqtt_server = "735a3a55afbc494aa1b11243344ae022.s1.eu.hivemq.cloud";
const int mqtt_port = 8883; // Cổng bảo mật

// 3. Tài khoản (Tạo trong Access Management của HiveMQ)
const char* mqtt_user = "danielfung"; 
const char* mqtt_pass = "Pgd05092004@";

const char* mqtt_topic = "iot/sensor/gas";

const int GAS_PIN = 34;   // Chân Analog cảm biến
const int BUZZER_PIN = 5; // Chân Còi (Sửa nếu cần)
const int THRESHOLD = 600; // Ngưỡng báo động

WiFiClientSecure espClient;
PubSubClient client(espClient);

void setup_wifi() {
  delay(10);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected");
}

void reconnect() {
  while (!client.connected()) {
    String clientId = "ESP32Client-" + String(random(0xffff), HEX);
    if (client.connect(clientId.c_str(), mqtt_user, mqtt_pass)) {
      Serial.println("MQTT Connected");
    } else {
      delay(5000);
    }
  }
}

void setup() {
  // WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); // Tắt chống sụt áp
  Serial.begin(115200);
  
  pinMode(GAS_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW); // Tắt còi ban đầu

  espClient.setInsecure(); // Bỏ qua check SSL để chạy nhanh
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
}

void loop() {
  if (!client.connected()) reconnect();
  client.loop();

  // Đọc cảm biến
  int gasValue = analogRead(GAS_PIN);

  // --- LOGIC TẠI CHỖ (LOCAL) ---
  if (gasValue > THRESHOLD) {
    digitalWrite(BUZZER_PIN, HIGH); // Hú còi
  } else {
    digitalWrite(BUZZER_PIN, LOW);  // Tắt còi
  }

  // --- GỬI LÊN CLOUD (Mỗi 2 giây) ---
  static unsigned long lastMsg = 0;
  if (millis() - lastMsg > 2000) {
    lastMsg = millis();
    char msg[10];
    snprintf(msg, 10, "%d", gasValue);
    client.publish(mqtt_topic, msg);
    Serial.printf("Gas: %d\n", gasValue);
  }
}