// dungeon-master on a Cheap Yellow Display.
//
// The board is a thin terminal: it draws what the bridge sends and posts back
// which button was pressed. It holds no Catalyst credential, parses no game
// state, and measures no text -- the bridge pre-wraps every line for this exact
// panel, because a full scene is about twice what fits on it.
//
// Boot runs a visible self-test ladder, so a failure says WHERE it is rather
// than just showing a blank screen:
//
//   1 display   a test pattern and this text
//   2 touch     raw coordinates, also printed to serial for calibration
//   3 wifi      associate, show the IP
//   4 bridge    GET /ping
//   5 game      GET /scene, then play
//
// Flash:   pio run -t upload && pio device monitor

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <XPT2046_Touchscreen.h>

#include "secrets.h"

// ---------------------------------------------------------------- display ---
TFT_eSPI tft = TFT_eSPI();

#define C_BG      TFT_BLACK
#define C_TITLE   TFT_YELLOW
#define C_RULE    TFT_ORANGE     // verbatim lines: the game as referee
#define C_PROSE   TFT_LIGHTGREY
#define C_BTN     0x02B5         // dark slate
#define C_BTN_TXT TFT_CYAN
#define C_HUD     TFT_GREENYELLOW
#define C_OK      TFT_GREEN
#define C_FAIL    TFT_RED

static const int SCR_W = 240, SCR_H = 320;
static const int ROW_H = 18, TITLE_H = 22, HUD_H = 18;
static const int BTN_H = 30, BTN_GAP = 3;

// ------------------------------------------------------------------ touch ---
SPIClass touchSPI(HSPI);
XPT2046_Touchscreen ts(CYD_TOUCH_CS, CYD_TOUCH_IRQ);

// Nominal calibration. The raw XPT2046 range varies per unit, so rung 2 prints
// the raw values: read the corners off the serial monitor and correct these.
static int TS_MINX = 240, TS_MAXX = 3800;
static int TS_MINY = 200, TS_MAXY = 3800;

struct Btn { String k, label; int x, y, w, h; };
static Btn  buttons[10];
static int  nButtons = 0;
static bool haveMore = false;
static String slot = GAME_SLOT;

// ------------------------------------------------------------------- utils ---
static void line(int row, const char *s, uint16_t colour) {
  tft.setTextColor(colour, C_BG);
  tft.drawString(s, 6, 4 + row * ROW_H, 2);
}

static void banner(const char *s, uint16_t colour = C_TITLE) {
  tft.fillRect(0, 0, SCR_W, TITLE_H, C_BG);
  tft.setTextColor(colour, C_BG);
  tft.drawString(s, 6, 3, 2);
}

// ---------------------------------------------------------- the self test ---
static int probeRow = 1;
static void probe(const char *what, bool ok, const char *detail = "") {
  char buf[64];
  snprintf(buf, sizeof buf, "%-9s %s %s", what, ok ? "ok" : "FAIL", detail);
  line(probeRow++, buf, ok ? C_OK : C_FAIL);
  Serial.printf("[probe] %s\n", buf);
}

static bool connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    tft.drawString(".", 6 + (i % 40) * 5, 4 + probeRow * ROW_H, 2);
  }
  return WiFi.status() == WL_CONNECTED;
}

static bool httpGet(const String &path, String &body) {
  HTTPClient http;
  http.setTimeout(20000);
  String url = String("http://") + BRIDGE_HOST + ":" + BRIDGE_PORT + path;
  if (!http.begin(url)) return false;
  int code = http.GET();
  if (code == 200) body = http.getString();
  http.end();
  return code == 200;
}

static bool httpPost(const String &path, const String &payload, String &body) {
  HTTPClient http;
  // HTTPClient::setTimeout takes a uint16_t, so 65.5s is the ceiling. A turn
  // is normally 2-9s (a model writes the prose), but a campfire rest blocks the
  // bridge for its whole duration -- so keep DM_REST_SECONDS under a minute,
  // or make the bridge return immediately and have the device poll.
  http.setTimeout(60000);
  String url = String("http://") + BRIDGE_HOST + ":" + BRIDGE_PORT + path;
  if (!http.begin(url)) return false;
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(payload);
  if (code == 200) body = http.getString();
  http.end();
  return code == 200;
}

// ------------------------------------------------------------- the screen ---
static void drawScene(JsonDocument &doc) {
  tft.fillScreen(C_BG);

  banner(doc["title"] | "");

  // Buttons are bottom-anchored, so the text area is whatever is left. The
  // bridge already trimmed the prose to fit, but clip anyway: never let prose
  // overwrite a rule line or a button.
  JsonArray btns = doc["buttons"].as<JsonArray>();
  nButtons = 0;
  int rows = (btns.size() + 1) / 2;
  int btnTop = SCR_H - HUD_H - rows * (BTN_H + BTN_GAP);

  int y = TITLE_H + 4;
  tft.setTextColor(C_RULE, C_BG);
  for (JsonVariant v : doc["rule"].as<JsonArray>()) {
    if (y + ROW_H > btnTop) break;
    tft.drawString(v.as<const char *>(), 6, y, 2);
    y += ROW_H;
  }
  tft.setTextColor(C_PROSE, C_BG);
  for (JsonVariant v : doc["prose"].as<JsonArray>()) {
    if (y + ROW_H > btnTop) break;
    tft.drawString(v.as<const char *>(), 6, y, 2);
    y += ROW_H;
  }

  haveMore = doc["more"] | false;
  if (haveMore && y + ROW_H <= btnTop) {
    tft.setTextColor(C_BTN_TXT, C_BG);
    tft.drawString("...", 6, y, 2);
  }

  // Two per row. The count changes every scene -- a choice already taken
  // disappears -- so this is laid out fresh each time, never a fixed grid.
  int i = 0;
  for (JsonVariant v : btns) {
    int col = i % 2, row = i / 2;
    int w = (SCR_W - 3 * BTN_GAP) / 2;
    int x = BTN_GAP + col * (w + BTN_GAP);
    int by = btnTop + row * (BTN_H + BTN_GAP);

    tft.fillRoundRect(x, by, w, BTN_H, 4, C_BTN);
    tft.setTextColor(C_BTN_TXT, C_BTN);
    String label = v["label"].as<String>();
    // Trim to the button, keeping the start: the first words identify it.
    while (label.length() > 1 && tft.textWidth(label, 2) > w - 8)
      label.remove(label.length() - 1);
    tft.drawString(label, x + 4, by + 7, 2);

    if (nButtons < 10) {
      buttons[nButtons++] = {v["k"].as<String>(), v["label"].as<String>(),
                             x, by, w, BTN_H};
    }
    i++;
  }

  tft.fillRect(0, SCR_H - HUD_H, SCR_W, HUD_H, C_BG);
  tft.setTextColor(C_HUD, C_BG);
  tft.drawString(doc["hud"] | "", 6, SCR_H - HUD_H + 2, 2);
}

static bool fetchAndDraw(const String &path, const String &post = "") {
  String body;
  bool ok = post.length() ? httpPost(path, post, body) : httpGet(path, body);
  if (!ok) {
    banner("the dungeon did not answer", C_FAIL);
    return false;
  }
  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    banner("bad reply from bridge", C_FAIL);
    return false;
  }
  if (doc["error"].is<const char *>()) {
    banner(doc["error"], C_FAIL);
    return false;
  }
  drawScene(doc);
  return true;
}

static void spinner(const char *label) {
  tft.fillRect(0, 0, SCR_W, TITLE_H, C_BG);
  tft.setTextColor(C_BTN_TXT, C_BG);
  tft.drawString(label, 6, 3, 2);   // silence reads as a hang
}

// ------------------------------------------------------------------ setup ---
void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);          // or the board looks dead
  tft.init();
  tft.setRotation(0);                  // portrait, 240x320
  tft.fillScreen(C_BG);

  banner("dungeon-master  self test");
  probe("display", true, "ILI9341");

  touchSPI.begin(CYD_TOUCH_CLK, CYD_TOUCH_MISO, CYD_TOUCH_MOSI, CYD_TOUCH_CS);
  bool tok = ts.begin(touchSPI);
  ts.setRotation(0);
  probe("touch", tok, "tap to show xy");

  // A window to prod the screen in. The raw numbers go to serial and are what
  // the calibration constants above should be set from: the XPT2046 range
  // varies per unit, so the defaults are nominal until someone touches glass.
  // Ends early once it has seen four distinct touches, so a calibrated board
  // does not sit here on every boot.
  line(probeRow, "touch 4 corners ->", C_TITLE);
  unsigned long until = millis() + 30000;
  int seen = 0;
  while (millis() < until && seen < 4) {
    if (ts.touched()) {
      TS_Point p = ts.getPoint();
      char buf[48];
      snprintf(buf, sizeof buf, "raw x=%4d y=%4d z=%3d", p.x, p.y, p.z);
      line(probeRow, buf, C_BTN_TXT);
      Serial.printf("[touch] %s\n", buf);
      seen++;
      while (ts.touched()) delay(20);   // one reading per press
    }
    delay(30);
  }
  probeRow++;

  probe("wifi", connectWifi(), WiFi.localIP().toString().c_str());
  if (WiFi.status() != WL_CONNECTED) {
    line(probeRow + 1, "check 2.4GHz SSID", C_FAIL);
    return;
  }

  String body;
  bool pong = httpGet("/ping", body);
  probe("bridge", pong, pong ? "/ping ok" : BRIDGE_HOST);
  if (!pong) {
    line(probeRow + 1, "is the bridge running?", C_FAIL);
    return;
  }

  line(probeRow + 1, "tap to enter the dungeon", C_TITLE);
  while (!ts.touched()) delay(50);
  spinner("opening the dungeon...");
  fetchAndDraw("/scene?slot=" + slot);
}

// ------------------------------------------------------------------- loop ---
void loop() {
  if (!ts.touched()) { delay(30); return; }

  TS_Point p = ts.getPoint();
  int x = map(p.x, TS_MINX, TS_MAXX, 0, SCR_W);
  int y = map(p.y, TS_MINY, TS_MAXY, 0, SCR_H);
  Serial.printf("[tap] raw=%d,%d -> %d,%d\n", p.x, p.y, x, y);

  for (int i = 0; i < nButtons; i++) {
    Btn &b = buttons[i];
    if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
      tft.drawRoundRect(b.x, b.y, b.w, b.h, 4, C_BTN_TXT);   // tap feedback
      spinner("the dungeon considers...");
      JsonDocument req;
      req["slot"] = slot;
      req["k"] = b.k;
      String payload;
      serializeJson(req, payload);
      fetchAndDraw("/command", payload);
      while (ts.touched()) delay(20);   // wait for release, no double-fire
      return;
    }
  }
  delay(30);
}
