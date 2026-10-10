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

#include "secrets.h"
#include "touch.h"

// The BOOT button. Held through a reset it enters the bootloader, but a press
// while running is just a button -- the only one this board has.
#define PIN_BOOT 0

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
static const int ROW_H = 18, TITLE_H = 22, HUD_H = 18;  // font 2 is 16px tall
// 26, not 30: four rows of buttons at 30px cost 148px of the 320, leaving
// eight text rows; at 26 they cost 116 and leave nine. Mirrored in the
// bridge's layout.py -- if the two disagree the prose gets clipped.
static const int BTN_H = 26, BTN_GAP = 3;

// ------------------------------------------------------------------ touch ---
// Touch is driven by src/touch.h -- software SPI, see the note there.

// Nominal calibration. The raw XPT2046 range varies per unit, so rung 2 prints
// the raw values: read the corners off the serial monitor and correct these.
// Measured on this board by the guided calibration below, then baked in.
// X is reversed -- screen X rises as the raw value falls -- which is why MINX
// is the larger number. Arduino's map() interpolates a reversed range fine, so
// the inversion needs no special case.
static int TS_MINX = 1932, TS_MAXX = 209;
static int TS_MINY = 101,  TS_MAXY = 1886;
static bool TS_SWAP = false;                 // screen X comes from raw X here

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
// The map, drawn from the bridge's fog-of-war cells. Only rooms the player has
// stood in carry a name; an unexplored neighbour is a "?"; the vault is simply
// absent until the door opens, so the map cannot give the secret away.
static void drawMap(JsonDocument &doc) {
  tft.fillScreen(C_BG);
  banner("the map");

  JsonObject m = doc["map"].as<JsonObject>();
  int x0 = m["x0"] | 0, y0 = m["y0"] | 0;
  int w = m["w"] | 1, h = m["h"] | 1;

  const int top = TITLE_H + 6;
  const int bottom = SCR_H - HUD_H - (BTN_H + BTN_GAP) - 4;
  const int availW = SCR_W - 8, availH = bottom - top;
  int cw = availW / w, ch = availH / h;
  if (cw > 76) cw = 76;                 // keep cells from sprawling
  if (ch > 60) ch = 60;
  int ox = (SCR_W - cw * w) / 2;
  int oy = top + (availH - ch * h) / 2;

  for (JsonVariant v : m["cells"].as<JsonArray>()) {
    int cx = v["x"] | 0, cy = v["y"] | 0;
    bool seen = v["seen"] | false, here = v["here"] | false;
    // y grows north in the world, down the screen here.
    int px = ox + (cx - x0) * cw;
    int py = oy + ((y0 + h - 1) - cy) * ch;

    tft.fillRoundRect(px + 2, py + 2, cw - 4, ch - 4, 3,
                      seen ? C_BTN : C_BG);
    tft.drawRoundRect(px + 2, py + 2, cw - 4, ch - 4, 3,
                      here ? C_TITLE : (seen ? C_BTN_TXT : C_PROSE));

    String label = v["label"].as<String>();
    if (!seen) {
      tft.setTextColor(C_PROSE, C_BG);
      tft.drawString("?", px + cw / 2 - 3, py + ch / 2 - 8, 2);
      continue;
    }
    // Two lines if the name does not fit on one.
    tft.setTextColor(here ? C_TITLE : C_BTN_TXT, C_BTN);
    int maxw = cw - 10;
    if (tft.textWidth(label, 2) <= maxw) {
      tft.drawString(label, px + 5, py + ch / 2 - 8, 2);
    } else {
      int cut = label.length();
      while (cut > 1 && tft.textWidth(label.substring(0, cut), 2) > maxw) cut--;
      int sp = label.lastIndexOf(' ', cut);
      if (sp < 1) sp = cut;
      tft.drawString(label.substring(0, sp), px + 5, py + ch / 2 - 16, 2);
      String rest = label.substring(sp + 1);
      while (rest.length() > 1 && tft.textWidth(rest, 2) > maxw)
        rest.remove(rest.length() - 1);
      tft.drawString(rest, px + 5, py + ch / 2, 2);
    }
    if (here) {
      tft.fillCircle(px + cw - 10, py + 10, 3, C_TITLE);
    }
  }

  // The one button, full width, so "back" is unmissable.
  nButtons = 0;
  int by = SCR_H - HUD_H - BTN_H - BTN_GAP;
  tft.fillRoundRect(BTN_GAP, by, SCR_W - 2 * BTN_GAP, BTN_H, 4, C_BTN);
  tft.setTextColor(C_BTN_TXT, C_BTN);
  tft.drawString("back", BTN_GAP + 6, by + 5, 2);
  buttons[nButtons++] = {"back", "back", BTN_GAP, by, SCR_W - 2 * BTN_GAP, BTN_H};

  tft.fillRect(0, SCR_H - HUD_H, SCR_W, HUD_H, C_BG);
  tft.setTextColor(C_HUD, C_BG);
  tft.drawString(doc["hud"] | "", 6, SCR_H - HUD_H + 2, 2);
}

static void drawScene(JsonDocument &doc) {
  if (doc["map"].is<JsonObject>()) { drawMap(doc); return; }
  tft.fillScreen(C_BG);

  banner(doc["title"] | "");
  // The title bar is not a button, so it is free real estate -- and tapping it
  // opens the map. Label it, or the gesture is a secret rather than a feature.
  tft.setTextColor(C_BTN_TXT, C_BG);
  tft.drawString("[map]", SCR_W - 40, 3, 2);

  // Buttons are bottom-anchored, so the text area is whatever is left. The
  // bridge already trimmed the prose to fit, but clip anyway: never let prose
  // overwrite a rule line or a button.
  JsonArray btns = doc["buttons"].as<JsonArray>();
  nButtons = 0;
  // Count rows the same way the bridge does: wide buttons one per row, narrow
  // ones two. Disagreeing with the bridge here is what clips the prose.
  int nWide = 0, nNarrow = 0;
  for (JsonVariant v : btns) ((v["wide"] | false) ? nWide : nNarrow)++;
  int rows = nWide + (nNarrow + 1) / 2;
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

  // Two widths. Directions are short and go two per row; numbered choices are
  // sentences and get a full row each, which is what finally uses the whole
  // 240px instead of truncating every choice to half of it.
  //
  // The count and the mix change every scene -- a choice already taken
  // disappears -- so this is laid out fresh each time, never a fixed grid.
  int by = btnTop;
  int pendingNarrowX = -1;          // a half-width slot waiting for a partner
  nButtons = 0;
  for (JsonVariant v : btns) {
    bool wide = v["wide"] | false;
    int x, w;
    if (wide) {
      if (pendingNarrowX >= 0) { by += BTN_H + BTN_GAP; pendingNarrowX = -1; }
      x = BTN_GAP;
      w = SCR_W - 2 * BTN_GAP;
    } else if (pendingNarrowX < 0) {
      w = (SCR_W - 3 * BTN_GAP) / 2;
      x = BTN_GAP;
      pendingNarrowX = x + w + BTN_GAP;
    } else {
      w = (SCR_W - 3 * BTN_GAP) / 2;
      x = pendingNarrowX;
      pendingNarrowX = -1;
    }

    tft.fillRoundRect(x, by, w, BTN_H, 4, C_BTN);
    String label = v["label"].as<String>();

    // "N  Hall of Teeth": draw the direction letter in the title colour so the
    // way out is readable at a glance. The destination name alone never said
    // which direction it was.
    int tx = x + 5;
    if (!wide && label.length() > 3 && label[1] == ' ' && label[2] == ' ' &&
        isupper(label[0])) {
      tft.setTextColor(C_TITLE, C_BTN);
      tft.drawString(label.substring(0, 1), tx, by + 7, 2);
      tx += tft.textWidth("N  ", 2);
      label = label.substring(3);
    }
    tft.setTextColor(C_BTN_TXT, C_BTN);
    while (label.length() > 1 && tft.textWidth(label, 2) > (x + w - 4) - tx)
      label.remove(label.length() - 1);
    tft.drawString(label, tx, by + 7, 2);

    if (nButtons < 10) {
      buttons[nButtons++] = {v["k"].as<String>(), v["label"].as<String>(),
                             x, by, w, BTN_H};
    }
    if (wide || pendingNarrowX < 0) by += BTN_H + BTN_GAP;
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

  // Report real font metrics once, so the bridge wraps to the width this
  // panel actually has instead of an assumed column count. Guessed numbers are
  // what cut text off and left the right-hand side empty.
  Serial.printf("[font] f2 height=%d  \"M\"=%d  \"i\"=%d  24x\"n\"=%d  screen=%dx%d\n",
                tft.fontHeight(2), tft.textWidth("M", 2), tft.textWidth("i", 2),
                tft.textWidth("nnnnnnnnnnnnnnnnnnnnnnnn", 2), SCR_W, SCR_H);
  Serial.printf("[font] sample sentence width=%d for %d chars\n",
                tft.textWidth("the lodestone drinks 2 health", 2), 29);
  banner("dungeon-master  self test");
  probe("display", true, "ILI9341");

  pinMode(PIN_BOOT, INPUT_PULLUP);
  Serial.printf("[boot] GPIO0 reads %d (1 = released; press it to see 0)\n",
                digitalRead(PIN_BOOT));

  touchInit();
  uint16_t tz = 0;
  touchRead(nullptr, nullptr, &tz);
  probe("touch", true, "bit-bang");

  // Calibration is opt-in now that this board's numbers are baked in above:
  // hold a finger on the screen through reset to redo it. Otherwise the board
  // goes straight to the game, which is what you want every other time.
  bool wantCal = touchRead(nullptr, nullptr, nullptr);
  if (wantCal) {

  // GUIDED CALIBRATION. Three targets: top-left, top-right, bottom-left.
  // TL->TR moves in screen X only, TL->BL in screen Y only, so whichever raw
  // axis changes across each pair IS that screen axis -- which settles both
  // the swap and the direction. Tapping four corners cannot: every corner pair
  // is a diagonal, and a diagonal changes both axes at once.
  struct Target { int x, y; const char *name; };
  Target targets[3] = {{20, 20, "top-left"}, {SCR_W - 20, 20, "top-right"},
                       {20, SCR_H - 20, "bottom-left"}};
  uint16_t rawX[3] = {0, 0, 0}, rawY[3] = {0, 0, 0};
  bool calOk = true;

  for (int i = 0; i < 3; i++) {
    tft.fillScreen(C_BG);
    banner("calibration");
    tft.setTextColor(C_PROSE, C_BG);
    tft.drawString("tap the circle", 6, 30, 2);
    tft.drawString(targets[i].name, 6, 48, 2);
    tft.drawCircle(targets[i].x, targets[i].y, 10, C_TITLE);
    tft.drawCircle(targets[i].x, targets[i].y, 3, C_TITLE);

    unsigned long until = millis() + 25000;
    bool got = false;
    while (millis() < until && !got) {
      uint16_t x, y, z;
      if (touchRead(&x, &y, &z)) {
        rawX[i] = x; rawY[i] = y; got = true;
        Serial.printf("[cal] %-11s raw x=%4u y=%4u\n", targets[i].name, x, y);
        tft.fillCircle(targets[i].x, targets[i].y, 6, C_OK);
        while (touchRead(nullptr, nullptr, nullptr)) delay(20);
        delay(250);
      }
      delay(20);
    }
    if (!got) { calOk = false; break; }
  }

  tft.fillScreen(C_BG);
  probeRow = 1;
  banner("dungeon-master  self test");
  probe("display", true, "ILI9341");
  probe("touch", true, "bit-bang");

  if (calOk) {
    // Which raw axis tracked the horizontal move?
    int dHorizX = abs((int)rawX[1] - (int)rawX[0]);
    int dHorizY = abs((int)rawY[1] - (int)rawY[0]);
    TS_SWAP = dHorizY > dHorizX;

    // Extrapolate each axis from its two samples out to the screen edges, so
    // the mapping covers 0..SCR rather than only the tapped inset.
    int sx0 = TS_SWAP ? rawY[0] : rawX[0];      // at screen x = 20
    int sx1 = TS_SWAP ? rawY[1] : rawX[1];      // at screen x = SCR_W - 20
    int sy0 = TS_SWAP ? rawX[0] : rawY[0];      // at screen y = 20
    int sy1 = TS_SWAP ? rawX[2] : rawY[2];      // at screen y = SCR_H - 20

    float px = (float)(sx1 - sx0) / (float)(SCR_W - 40);
    float py = (float)(sy1 - sy0) / (float)(SCR_H - 40);
    TS_MINX = (int)(sx0 - px * 20);
    TS_MAXX = (int)(sx1 + px * 20);
    TS_MINY = (int)(sy0 - py * 20);
    TS_MAXY = (int)(sy1 + py * 20);

    Serial.printf("[cal] swap=%d  X %d..%d  Y %d..%d\n",
                  TS_SWAP, TS_MINX, TS_MAXX, TS_MINY, TS_MAXY);
    Serial.println("[cal] ^ bake these into main.cpp to skip calibration");
    char buf[48];
    snprintf(buf, sizeof buf, "swap=%d x %d..%d", TS_SWAP, TS_MINX, TS_MAXX);
    probe("calib", true, buf);
  } else {
    probe("calib", false, "timed out, using defaults");
  }

  } else {
    probe("calib", true, "baked in");
  }

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
  while (!touchRead(nullptr, nullptr, nullptr)) delay(50);
  spinner("opening the dungeon...");
  fetchAndDraw("/scene?slot=" + slot);
}

// ------------------------------------------------------------------- loop ---
void loop() {
  // The BOOT button is the board's only physical button, and opens the map
  // too, for anyone who would rather press a thing than tap glass.
  if (digitalRead(PIN_BOOT) == LOW) {
    spinner("the map...");
    JsonDocument req;
    req["slot"] = slot; req["k"] = "map";
    String payload; serializeJson(req, payload);
    fetchAndDraw("/command", payload);
    while (digitalRead(PIN_BOOT) == LOW) delay(20);
    return;
  }

  uint16_t rx, ry, rz;
  if (!touchRead(&rx, &ry, &rz)) { delay(30); return; }

  int x = map(TS_SWAP ? ry : rx, TS_MINX, TS_MAXX, 0, SCR_W);
  int y = map(TS_SWAP ? rx : ry, TS_MINY, TS_MAXY, 0, SCR_H);
  x = constrain(x, 0, SCR_W - 1);
  y = constrain(y, 0, SCR_H - 1);
  Serial.printf("[tap] raw=%u,%u -> %d,%d\n", rx, ry, x, y);

  // A tap on the title bar asks for the map. Checked before the buttons,
  // since no button is drawn up there.
  if (y < TITLE_H) {
    spinner("the map...");
    JsonDocument req;
    req["slot"] = slot; req["k"] = "map";
    String payload; serializeJson(req, payload);
    fetchAndDraw("/command", payload);
    while (touchRead(nullptr, nullptr, nullptr)) delay(20);
    return;
  }

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
      while (touchRead(nullptr, nullptr, nullptr)) delay(20);  // await release
      return;
    }
  }
  delay(30);
}
