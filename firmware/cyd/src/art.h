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

#include "dragon_sprite.h"

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
// What is in the vault, drawn as what you would actually see of it.
//
// Three attempts at a dragon were abandoned: a large shaded one read as a
// blob, a 28px head read as nothing, and a triangle silhouette read as a
// solid mass. The honest conclusion is that a convincing animal is beyond
// what can be hand-plotted here, and a shape nobody recognises is worse than
// no shape.
//
// So this draws the dark instead. Two amber slit eyes, a suggestion of a mass
// around them a shade above black, and nothing else -- which is the truthful
// view of something enormous lying in an unlit room, and needs no draughting
// talent to land. The prose below says the word "dragon"; the picture only has
// to make the room feel occupied.
//
// If you want an actual dragon, tools/png2sprite.py converts any small image
// into a 1-bit sprite that drawBitmap can take -- see its header.
// ---------------------------------------------------------------------------
inline void artVaultDark(TFT_eSPI &tft, int x, int y, int w, int h) {
  tft.fillRect(x, y, w, h, ART_VOID);

  // A real dragon, supplied as a picture and converted by tools/png2sprite.py
  // -- 585 bytes, no SD card. This is the thing four attempts at plotting
  // primitives could not produce: the drawing was always the weak link, never
  // the medium, and a 1-bit sprite moves that problem to someone who can draw.
  if (DRAGON_H <= h) {
    int dx = x + (w - DRAGON_W) / 2;
    int dy = y + (h - DRAGON_H) / 2;
    tft.drawBitmap(dx, dy, DRAGON, DRAGON_W, DRAGON_H, ART_SCALE);
    // One warm eye, placed on the head rather than guessed: the silhouette has
    // no features, so the only thing that makes it look alive is this.
    tft.fillCircle(dx + DRAGON_W * 32 / 72, dy + DRAGON_H * 14 / 65, 2, ART_EYE);
    return;
  }

  // Not enough room for the sprite: fall back to the dark and two eyes, which
  // was what stood here before and still reads as something enormous.
  const int cx = x + w / 2, cy = y + h / 2;

  // The mass: barely-there wedges, a shade above black, so the eye reads bulk
  // without being asked to identify anatomy.
  tft.fillTriangle(cx - w / 3, y + h, cx - w / 8, cy - h / 6,
                   cx + w / 10, y + h, 0x1061);
  tft.fillTriangle(cx + w / 12, y + h, cx + w / 4, cy - h / 8,
                   cx + w / 3, y + h, 0x1061);
  tft.fillTriangle(cx - w / 2, y + h, cx - w / 3, cy + h / 6,
                   cx - w / 6, y + h, 0x0820);

  // The eyes. Slits, not circles: a vertical pupil is the whole difference
  // between "lamps" and "something awake".
  const int eyeDx = w / 9, eyeR = h / 7;
  for (int side = -1; side <= 1; side += 2) {
    int ex = cx + side * eyeDx;
    tft.fillCircle(ex, cy, eyeR, ART_EYE);
    tft.fillCircle(ex, cy, eyeR * 2 / 3, 0xFC00);        // hotter centre
    tft.fillRect(ex - 1, cy - eyeR, 2, eyeR * 2, ART_VOID);  // the slit
  }
  // A faint glow under each, as if they are the only light in there.
  tft.drawFastHLine(cx - eyeDx - eyeR, cy + eyeR + 2, eyeR * 2, 0x6180);
  tft.drawFastHLine(cx + eyeDx - eyeR, cy + eyeR + 2, eyeR * 2, 0x6180);
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
