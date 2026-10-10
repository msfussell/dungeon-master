// The dragon and the scroll, drawn rather than stored.
//
// No SD card and no image file: a 240x320 bitmap is ~150KB in RGB565, which
// will not fit the flash this sketch has left. Primitives cost a few hundred
// bytes of code and scale to whatever rectangle they are handed, so the same
// picture works in the 110px strip left over in the vault and on a full
// screen at the ending.
//
// It is a side view: the dragon coiled in a C around a glowing scroll, head
// low and turned outward, watching whoever came in.

#pragma once
#include <TFT_eSPI.h>

// Iron scales, warm parchment, and a glow that reads as light rather than paint.
#define ART_DRAGON   0x6B4D      // iron grey-green
#define ART_DRAGON_D 0x4208      // its shadowed side
#define ART_SPINE    0x9CD3      // spines and claws, lighter
#define ART_EYE      0xFD20      // amber, the only warm thing in the beast
#define ART_SCROLL   0xEF5B      // old paper
#define ART_SCROLL_D 0xB596      // the rolled edge
#define ART_GLOW1    0x8200      // dim gold
#define ART_GLOW2    0xC300      // mid
#define ART_GLOW3    0xFEA0      // bright

// One segment of the coiled body: a circle, so overlapping them makes a thick
// smooth curve without any curve maths.
inline void artCoilSegment(TFT_eSPI &tft, int cx, int cy, int r) {
  tft.fillCircle(cx, cy, r, ART_DRAGON);
  tft.fillCircle(cx - r / 3, cy + r / 3, r * 2 / 3, ART_DRAGON_D);
}

// cx,cy is the centre of the coil; `s` scales everything, so one routine
// serves both the inline strip and the full-screen ending.
inline void artDragonAndScroll(TFT_eSPI &tft, int cx, int cy, int s) {
  // ---- the glow behind the scroll, brightest at the middle ----
  tft.fillCircle(cx, cy, s * 38 / 10, ART_GLOW1);
  tft.fillCircle(cx, cy, s * 28 / 10, ART_GLOW2);
  tft.fillCircle(cx, cy, s * 18 / 10, ART_GLOW3);

  // ---- the coil: segments around a C, open at the right where the head is --
  // Angles in degrees, walking anticlockwise from the lower right.
  const int coilR = s * 46 / 10;
  const int body  = s * 11 / 10;
  for (int a = 35; a <= 300; a += 11) {
    float rad = a * 0.01745329f;
    int px = cx + (int)(cosf(rad) * coilR);
    int py = cy - (int)(sinf(rad) * coilR * 0.82f);   // flatten: it is coiled, not a ball
    artCoilSegment(tft, px, py, body);
  }

  // ---- spines along the outside of the coil ----
  for (int a = 60; a <= 280; a += 22) {
    float rad = a * 0.01745329f;
    int bx = cx + (int)(cosf(rad) * (coilR + body * 0.6f));
    int by = cy - (int)(sinf(rad) * (coilR + body * 0.6f) * 0.82f);
    int tx = cx + (int)(cosf(rad) * (coilR + body * 1.8f));
    int ty = cy - (int)(sinf(rad) * (coilR + body * 1.8f) * 0.82f);
    tft.fillTriangle(bx - s / 4, by, bx + s / 4, by, tx, ty, ART_SPINE);
  }

  // ---- the scroll, lying across the middle of the coil ----
  int sw = s * 30 / 10, sh = s * 8 / 10;
  tft.fillRect(cx - sw / 2, cy - sh / 2, sw, sh, ART_SCROLL);
  // rolled ends
  tft.fillCircle(cx - sw / 2, cy, sh / 2 + 1, ART_SCROLL_D);
  tft.fillCircle(cx + sw / 2, cy, sh / 2 + 1, ART_SCROLL_D);
  tft.fillCircle(cx - sw / 2, cy, sh / 4, ART_SCROLL);
  tft.fillCircle(cx + sw / 2, cy, sh / 4, ART_SCROLL);
  // writing, suggested not spelled
  for (int i = 1; i <= 3; i++) {
    int ly = cy - sh / 2 + i * sh / 4;
    tft.drawFastHLine(cx - sw / 3, ly, sw * 2 / 3 - (i == 3 ? sw / 4 : 0), ART_SCROLL_D);
  }

  // ---- the head, low and to the right, turned out of the coil ----
  int hx = cx + coilR + body / 2, hy = cy + (int)(s * 1.5f);
  tft.fillCircle(hx, hy, body * 11 / 10, ART_DRAGON);          // skull
  tft.fillTriangle(hx, hy - body / 2, hx, hy + body / 2,
                   hx + body * 23 / 10, hy + body / 4, ART_DRAGON);  // snout
  tft.fillTriangle(hx - body / 2, hy - body, hx + body / 3, hy - body / 3,
                   hx - body * 3 / 2, hy - body * 2, ART_SPINE);     // horn
  tft.fillCircle(hx + body / 3, hy - body / 3, s / 4 + 1, ART_EYE);  // the eye
  // a wisp of breath, because a still dragon still breathes
  tft.drawFastHLine(hx + body * 24 / 10, hy + body / 4, s, ART_GLOW2);
  tft.drawFastHLine(hx + body * 26 / 10, hy + body / 4 + 2, s * 7 / 10, ART_GLOW1);

  // ---- tail, tapering away from the open end of the coil ----
  int tx0 = cx + (int)(cosf(35 * 0.01745329f) * coilR);
  int ty0 = cy - (int)(sinf(35 * 0.01745329f) * coilR * 0.82f);
  for (int i = 0; i < 5; i++) {
    int r = body - i * body / 5;
    if (r < 1) r = 1;
    tft.fillCircle(tx0 + i * body, ty0 - i * body / 2, r, ART_DRAGON);
  }
  tft.fillTriangle(tx0 + 5 * body, ty0 - 2 * body,
                   tx0 + 6 * body, ty0 - 3 * body,
                   tx0 + 4 * body, ty0 - 3 * body, ART_SPINE);
}

// Fit the drawing to whatever rectangle is free, so the caller never has to
// know how big it is.
inline void artDragonFit(TFT_eSPI &tft, int x, int y, int w, int h) {
  int s = (w < h * 2 ? w : h * 2) / 12;
  if (s < 3) s = 3;
  artDragonAndScroll(tft, x + w / 2, y + h / 2, s);
}
