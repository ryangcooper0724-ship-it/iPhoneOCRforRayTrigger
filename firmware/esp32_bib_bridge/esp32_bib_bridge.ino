/*
 * ESP32 ゼッケン中継ブリッジ（HTTPS版）
 *
 * iPhoneからのHTTP POST(JSON)をWi-Fi APモードで受信し、
 * 中身を一切加工せずUSBシリアルへそのまま転送するだけの最小構成。
 * JSONのパース・妥当性検証はPC側(serial_input/bib_source.py)で行う。
 *
 * Web版アプリ(GitHub Pages, https://)からのfetch()がMixed Content
 * （httpsページ→http通信）としてブロックされるため、ESP32側も自己署名証明書で
 * HTTPS化している。
 *
 * 証明書はビルド時にcert.h/private_key.hとして埋め込み済み（openssl + xxdで生成、
 * extras/esp32cert以下を参照）。起動時にその場で生成する方式(createSelfSignedCert)は
 * このライブラリ+ESP32の組み合わせでヒープ破損によるクラッシュループが発生したため
 * 採用していない。
 *
 * 初回はiPhoneのSafariで https://192.168.4.1/ を一度開き、証明書の警告画面で
 * 「詳細を表示」→「Webサイトを閲覧」を選んで信頼してから使うこと。
 */

#include <WiFi.h>
#include <HTTPSServer.hpp>
#include <SSLCert.hpp>
#include <HTTPRequest.hpp>
#include <HTTPResponse.hpp>

#include "cert.h"
#include "private_key.h"

using namespace httpsserver;

// 現場は閉鎖環境前提のためWPA2パスワード保護のみ。値は現場ごとに変更すること。
static const char *AP_SSID = "RayTrigOCR";
static const char *AP_PASSWORD = "1145141919810";

// iPhone側のリクエストヘッダに同じ値を設定し、誤接続元のPOSTを弾く。
static const char *EXPECTED_TOKEN = "fbdd66962e25160e855b7b083e49e9d6";

static const unsigned long SERIAL_BAUD = 115200;

SSLCert *cert;
HTTPSServer *secureServer;

void addCorsHeaders(HTTPResponse *res) {
  res->setHeader("Access-Control-Allow-Origin", "*");
  res->setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res->setHeader("Access-Control-Allow-Headers", "Content-Type, X-Bib-Token");
}

void handleBibOptions(HTTPRequest *req, HTTPResponse *res) {
  req->discardRequestBody();
  addCorsHeaders(res);
  res->setStatusCode(204);
  res->setStatusText("No Content");
}

void handleBibPost(HTTPRequest *req, HTTPResponse *res) {
  addCorsHeaders(res);

  std::string token = req->getHeader("X-Bib-Token");
  if (token != EXPECTED_TOKEN) {
    res->setStatusCode(401);
    res->setStatusText("Unauthorized");
    res->println("invalid token");
    return;
  }

  // リクエストボディをそのままシリアルへ転送する（パースはPC側で行う）。
  size_t length = req->getContentLength();
  std::string body;
  body.resize(length);
  size_t readBytes = req->readBytes((byte *)&body[0], length);
  body.resize(readBytes);

  Serial.println(body.c_str());

  res->println("ok");
}

void handleRoot(HTTPRequest *req, HTTPResponse *res) {
  // iPhoneで初回に証明書を信頼してもらうための確認用ページ。
  res->setHeader("Content-Type", "text/html; charset=utf-8");
  res->println("<!DOCTYPE html><html><body>");
  res->println("<h1>RayTrigOCR ESP32 Bridge</h1>");
  res->println("<p>This certificate is now trusted. You can use the BibScanner web app.</p>");
  res->println("</body></html>");
}

void handleNotFound(HTTPRequest *req, HTTPResponse *res) {
  req->discardRequestBody();
  res->setStatusCode(404);
  res->setStatusText("Not Found");
  res->println("not found");
}

void setup() {
  Serial.begin(SERIAL_BAUD);

  cert = new SSLCert(
      example_crt_DER, sizeof(example_crt_DER),
      example_key_DER, sizeof(example_key_DER));

  secureServer = new HTTPSServer(cert);

  WiFi.softAP(AP_SSID, AP_PASSWORD);

  ResourceNode *nodeRoot = new ResourceNode("/", "GET", &handleRoot);
  ResourceNode *nodeBibPost = new ResourceNode("/bib", "POST", &handleBibPost);
  ResourceNode *nodeBibOptions = new ResourceNode("/bib", "OPTIONS", &handleBibOptions);
  ResourceNode *node404 = new ResourceNode("", "GET", &handleNotFound);

  secureServer->registerNode(nodeRoot);
  secureServer->registerNode(nodeBibPost);
  secureServer->registerNode(nodeBibOptions);
  secureServer->setDefaultNode(node404);

  secureServer->start();
}

void loop() {
  secureServer->loop();
  delay(1);
}
