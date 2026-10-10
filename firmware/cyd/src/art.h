// Pictures drawn rather than stored. No SD card and no image files: a 240x320
// bitmap is ~150KB in RGB565 and this sketch has about 349KB of app flash
// left, so a few hundred bytes of primitives is the better trade.
//
// Lesson from the first attempt, which was scrapped: a big organic dragon made
// of circles reads as a blob. Primitives are good at ARCHITECTURE -- straight
// edges, arches, blocks, symmetry -- and at ICONS small enough that the eye
// fills in the rest. So the full-screen picture is a stone doorway, and the
// dragon is a 28px glyph.

#pragma once
#include <TFT_eSPI.h>

#define ART_STONE    0x5AEB
#define ART_STONE_D  0x31A6
#define ART_STONE_L  0x7BCF
#define ART_MORTAR   0x2104
#define ART_VOID     0x0000
#define ART_EYE      0xFD20
#define ART_FLAME    0xFC00
#define ART_FLAME_L  0xFEA0
#define ART_SCALE    0x5BEC
#define ART_PAPER    0xEF5B
#define ART_PAPER_D  0xB596
#define ART_GLOW     0xFEA0

// ---------------------------------------------------------------------------
// A dragon's head, about 28px. Small enough that suggestion does the work:
// a snout, a horn, an eye and a breath of fire is a dragon; the same shapes at
// 120px are a mess, which is what went wrong the first time.
// ---------------------------------------------------------------------------
inline void artMiniDragon(TFT_eSPI &tft, int x, int y, int s = 28) {
  int h = s / 2;                       // head radius-ish
  int cx = x + h, cy = y + h;

  // skull and jaw
  tft.fillCircle(cx, cy, h * 8 / 10, ART_SCALE);
  tft.fillTriangle(cx, cy - h / 3, cx, cy + h / 2,
                   cx + h * 15 / 10, cy + h / 5, ART_SCALE);   // snout
  tft.fillTriangle(cx - h / 5, cy - h * 7 / 10,
                   cx + h / 2, cy - h / 4,
                   cx - h * 9 / 10, cy - h * 15 / 10, ART_STONE_L);  // horn
  tft.fillTriangle(cx - h * 7 / 10, cy + h / 5,
                   cx - h * 4 / 10, cy + h * 9 / 10,
                   cx - h * 14 / 10, cy + h * 8 / 10, ART_SCALE);    // neck frill

  // the eye: the only warm thing in the animal
  tft.fillCircle(cx + h / 4, cy - h / 4, s / 9 + 1, ART_EYE);
  tft.drawPixel(cx + h / 4, cy - h / 4, ART_VOID);

  // a breath of fire, two tapering triangles
  int mx = cx + h * 15 / 10, my = cy + h / 5;
  tft.fillTriangle(mx, my - s / 10, mx, my + s / 10, mx + s / 2, my, ART_FLAME);
  tft.fillTriangle(mx, my - s / 16, mx, my + s / 16, mx + s / 3, my, ART_FLAME_L);
}

// A rolled scroll glyph, same scale, to sit beside it.
inline void artMiniScroll(TFT_eSPI &tft, int x, int y, int s = 28) {
  int w = s, h = s / 2;
  int cy = y + s / 2;
  tft.fillCircle(x + w / 2, cy, h * 9 / 10, ART_GLOW);     // its glow
  tft.fillRect(x + 3, cy - h / 3, w - 6, h * 2 / 3, ART_PAPER);
  tft.fillCircle(x + 3, cy, h / 3, ART_PAPER_D);
  tft.fillCircle(x + w - 3, cy, h / 3, ART_PAPER_D);
  tft.drawFastHLine(x + 6, cy - h / 8, w - 12, ART_PAPER_D);
  tft.drawFastHLine(x + 6, cy + h / 8, w - 16, ART_PAPER_D);
}

// ---------------------------------------------------------------------------
// The boot screen: a stone doorway with nothing good behind it.
// ---------------------------------------------------------------------------
inline void artDungeonEntrance(TFT_eSPI &tft, int w, int h) {
  tft.fillScreen(ART_MORTAR);

  // --- the wall, courses of block with staggered joints ---
  const int bh = 22;
  for (int row = 0, y = 0; y < h; row++, y += bh) {
    int offset = (row % 2) ? -26 : 0;
    for (int x = offset; x < w; x += 52) {
      tft.fillRect(x + 1, y + 1, 50, bh - 2,
                   (row + x / 52) % 3 == 0 ? ART_STONE_D : ART_STONE);
    }
  }

  // --- the doorway: a round arch over square jambs ---
  const int doorW = 128, doorH = 190;
  const int dx = (w - doorW) / 2;
  const int dy = h - doorH - 34;          // leave room for steps
  const int archR = doorW / 2;
  const int archCy = dy + archR;

  // voussoirs: a ring of pale stone around the opening
  tft.fillCircle(dx + archR, archCy, archR + 9, ART_STONE_L);
  tft.fillRect(dx - 9, archCy, doorW + 18, doorH - archR, ART_STONE_L);
  for (int a = 0; a <= 180; a += 20) {    // joints in the arch
    float r = a * 0.01745329f;
    tft.drawLine(dx + archR - (int)(cosf(r) * archR),
                 archCy - (int)(sinf(r) * archR),
                 dx + archR - (int)(cosf(r) * (archR + 9)),
                 archCy - (int)(sinf(r) * (archR + 9)), ART_MORTAR);
  }

  // the opening itself
  tft.fillCircle(dx + archR, archCy, archR, ART_VOID);
  tft.fillRect(dx, archCy, doorW, doorH - archR, ART_VOID);

  // --- two eyes, deep in it, a long way back ---
  int ey = archCy + 54;
  tft.fillCircle(dx + archR - 17, ey, 3, ART_EYE);
  tft.fillCircle(dx + archR + 17, ey, 3, ART_EYE);

  // --- steps down to the threshold ---
  for (int i = 0; i < 3; i++) {
    int sy = h - 34 + i * 11;
    int inset = i * 14;
    tft.fillRect(dx - 18 + inset, sy, doorW + 36 - inset * 2, 10, ART_STONE);
    tft.drawFastHLine(dx - 18 + inset, sy, doorW + 36 - inset * 2, ART_STONE_L);
  }

  // --- a hanging chain each side, because stillness needs something vertical --
  for (int side = -1; side <= 1; side += 2) {
    int cxx = dx + archR + side * (archR + 22);
    for (int yy = dy - 6; yy < dy + 60; yy += 9)
      tft.drawCircle(cxx, yy, 3, ART_STONE_L);
  }
}
