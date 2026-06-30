/*
 * ESP32 ゼッケン中継ブリッジ
 *
 * iPhoneからのHTTP POST(JSON)をWi-Fi APモードで受信し、
 * 中身を一切加工せずUSBシリアルへそのまま転送するだけの最小構成。
 * JSONのパース・妥当性検証はPC側(serial_input/bib_source.py)で行う。
 */

#include <WiFi.h>
#include <WebServer.h>

static const char *AP_SSID = "RayTrigOCR";
static const char *AP_PASSWORD = "1145141919810";
static const char *EXPECTED_TOKEN = "fbdd66962e25160e855b7b083e49e9d6";

WebServer server(80);

void handleBibPost() {
  if (server.header("X-Bib-Token") != EXPECTED_TOKEN) {
    server.send(401, "text/plain", "invalid token");
    return;
  }
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "empty body");
    return;
  }
  Serial.println(server.arg("plain"));
  server.send(200, "text/plain", "ok");
}

void handleNotFound() {
  server.send(404, "text/plain", "not found");
}

void setup() {
  Serial.begin(115200);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  server.on("/bib", HTTP_POST, handleBibPost);
  server.onNotFound(handleNotFound);
  server.begin();
}

void loop() {
  server.handleClient();
}
