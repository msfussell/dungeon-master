// A 40-line XPT2046 driver, bit-banged.
//
// Why not the library: XPT2046_Touchscreen on a SPIClass(HSPI) instance read
// nothing on this board -- 150 consecutive samples of z=0 with PENIRQ never
// going low, while a finger was on the glass. TFT_eSPI drives the display on
// pins 13/14/12/15, which are the ESP32's HSPI defaults, so a second HSPI
// instance for touch contends with it.
//
// Software SPI sidesteps the question entirely. It was validated on this exact
// board before being written here: on pins 25/32/39/33, z1 reads 0 untouched
// and ~410 held, with x/y in the expected 12-bit range. A touch poll every
// 30ms costs nothing, so the peripheral buys us no speed worth the ambiguity.

#pragma once
#include <Arduino.h>

#ifndef CYD_TOUCH_CLK
#define CYD_TOUCH_CLK 25
#define CYD_TOUCH_MOSI 32
#define CYD_TOUCH_MISO 39
#define CYD_TOUCH_CS 33
#endif

// Untouched reads 0 and a press reads several hundred, so this is a wide gate.
static const uint16_t TOUCH_Z_MIN = 100;

inline void touchInit() {
  pinMode(CYD_TOUCH_CLK, OUTPUT);
  pinMode(CYD_TOUCH_MOSI, OUTPUT);
  pinMode(CYD_TOUCH_MISO, INPUT);
  pinMode(CYD_TOUCH_CS, OUTPUT);
  digitalWrite(CYD_TOUCH_CS, HIGH);
  digitalWrite(CYD_TOUCH_CLK, LOW);
}

inline uint16_t touchXfer(uint8_t cmd) {
  digitalWrite(CYD_TOUCH_CS, LOW);
  for (int i = 7; i >= 0; i--) {
    digitalWrite(CYD_TOUCH_MOSI, (cmd >> i) & 1);
    digitalWrite(CYD_TOUCH_CLK, HIGH);
    delayMicroseconds(2);
    digitalWrite(CYD_TOUCH_CLK, LOW);
    delayMicroseconds(2);
  }
  uint16_t v = 0;
  for (int i = 0; i < 16; i++) {
    digitalWrite(CYD_TOUCH_CLK, HIGH);
    delayMicroseconds(2);
    v = (v << 1) | (digitalRead(CYD_TOUCH_MISO) ? 1 : 0);
    digitalWrite(CYD_TOUCH_CLK, LOW);
    delayMicroseconds(2);
  }
  digitalWrite(CYD_TOUCH_CS, HIGH);
  return v >> 4;                       // 12 significant bits
}

// Median of three, because a resistive panel is noisy at the moment of
// contact and a single bad sample would put a tap on the wrong button.
inline uint16_t med3(uint16_t a, uint16_t b, uint16_t c) {
  return a > b ? (b > c ? b : (a > c ? c : a)) : (a > c ? a : (b > c ? c : b));
}

inline bool touchRead(uint16_t *rx, uint16_t *ry, uint16_t *rz) {
  uint16_t z = touchXfer(0xB1);
  if (z < TOUCH_Z_MIN) { if (rz) *rz = z; return false; }
  uint16_t x = med3(touchXfer(0xD1), touchXfer(0xD1), touchXfer(0xD1));
  uint16_t y = med3(touchXfer(0x91), touchXfer(0x91), touchXfer(0x91));
  if (rx) *rx = x;
  if (ry) *ry = y;
  if (rz) *rz = z;
  return true;
}
