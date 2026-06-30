/*
 * ESP32 ゼッケン中継ブリッジ
 *
 * iPhoneからのHTTP POST(JSON)をWi-Fi APモードで受信し、
 * 中身を一切加工せずUSBシリアルへそのまま転送するだけの最小構成。
 * JSONのパース・妥当性検証はPC側(serial_input/bib_source.py)で行う。
 */

#include <WiFi.h>
#include <WebServer.h>

// 現場は閉鎖環境前提のためWPA2パスワード保護のみ。値は現場ごとに変更すること。
static const char *AP_SSID = "GYMKHANA_BIB";
static const char *AP_PASSWORD = "change_me_please";

// iPhone側のリクエストヘッダに同じ値を設定し、誤接続元のPOSTを弾く。
static const char *EXPECTED_TOKEN = "change_me_too";

static const int HTTP_PORT = 80;
static const unsigned long SERIAL_BAUD = 115200;

WebServer server(HTTP_PORT);

void handleBibPost() {
  if (server.header("X-Bib-Token") != EXPECTED_TOKEN) {
    server.send(401, "text/plain", "invalid token");
    return;
  }
  if (!server.hasArg("plain")) {
    server.send(400, "text/plain", "empty body");
    return;
  }

  String body = server.arg("plain");
  Serial.println(body);

  server.send(200, "text/plain", "ok");
}

void handleNotFound() {
  server.send(404, "text/plain", "not found");
}

void setup() {
  Serial.begin(SERIAL_BAUD);

  WiFi.softAP(AP_SSID, AP_PASSWORD);

  server.on("/bib", HTTP_POST, handleBibPost);
  server.onNotFound(handleNotFound);
  server.begin();
}

void loop() {
  server.handleClient();
}
