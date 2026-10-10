// Bit-bang an XPT2046 read on candidate pin sets.
//
// The library reported nothing and PENIRQ never went low, which means either
// the pins are wrong or the SPI peripheral is contended. This removes both
// variables: software SPI, one pin set at a time, raw 12-bit results.
//
// A live XPT2046 answers a Z1 (pressure) read with a small non-zero value
// untouched and a clearly larger one touched. All-zero or all-4095 means we
// are not talking to it.

#include <Arduino.h>

struct PinSet { const char *name; int clk, mosi, miso, cs; };

// The published CYD mapping first, then the plausible alternatives seen on
// other revisions of this board.
static PinSet sets[] = {
    {"published 25/32/39/33", 25, 32, 39, 33},
    {"alt  18/23/19/5  (VSPI/SD)", 18, 23, 19, 5},
    {"alt  14/13/12/33 (shared w/ TFT)", 14, 13, 12, 33},
    {"alt  25/32/39/26", 25, 32, 39, 26},
};

static uint16_t xfer(const PinSet &p, uint8_t cmd) {
  digitalWrite(p.cs, LOW);
  // 8-bit command, MSB first.
  for (int i = 7; i >= 0; i--) {
    digitalWrite(p.mosi, (cmd >> i) & 1);
    digitalWrite(p.clk, HIGH);
    delayMicroseconds(2);
    digitalWrite(p.clk, LOW);
    delayMicroseconds(2);
  }
  // 16 clocks back; the 12 significant bits are the top ones.
  uint16_t v = 0;
  for (int i = 0; i < 16; i++) {
    digitalWrite(p.clk, HIGH);
    delayMicroseconds(2);
    v = (v << 1) | (digitalRead(p.miso) ? 1 : 0);
    digitalWrite(p.clk, LOW);
    delayMicroseconds(2);
  }
  digitalWrite(p.cs, HIGH);
  return v >> 4;   // 12-bit result
}

static void setupSet(const PinSet &p) {
  pinMode(p.clk, OUTPUT);
  pinMode(p.mosi, OUTPUT);
  pinMode(p.miso, INPUT);
  pinMode(p.cs, OUTPUT);
  digitalWrite(p.cs, HIGH);
  digitalWrite(p.clk, LOW);
}

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("=== XPT2046 wiring probe: bit-banged, no libraries ===");
  Serial.println("Touch and HOLD the screen. Z should rise on the live pin set.");
  Serial.println();
}

void loop() {
  for (auto &p : sets) {
    setupSet(p);
    uint16_t z1 = xfer(p, 0xB1);   // pressure
    uint16_t x  = xfer(p, 0xD1);   // X
    uint16_t y  = xfer(p, 0x91);   // Y
    Serial.printf("[%-34s] z1=%4u x=%4u y=%4u\n", p.name, z1, x, y);
  }
  Serial.println("---");
  delay(1000);
}
