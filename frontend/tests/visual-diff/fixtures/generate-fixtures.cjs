/**
 * Generate test fixture PNGs for visual-comparator CLI integration testing.
 *
 * Creates:
 *   - header-design.png: Mock design screenshot (393x92, dark status bar + white header)
 *   - header-actual-good.png: Similar to design (~3% diff, should pass)
 *   - header-actual-bad.png: Visually different (~40% diff, should fail)
 *
 * Usage: node tests/visual-diff/fixtures/generate-fixtures.js
 */

const { PNG } = require('pngjs');
const fs = require('fs');
const path = require('path');

const WIDTH = 393;
const HEIGHT = 92;
const STATUS_BAR_HEIGHT = 54;

const OUTDIR = path.join(__dirname);

function createPNG(width, height) {
  const png = new PNG({ width, height });
  // Fill transparent
  for (let i = 0; i < png.data.length; i += 4) {
    png.data[i] = 0;
    png.data[i + 1] = 0;
    png.data[i + 2] = 0;
    png.data[i + 3] = 255;
  }
  return png;
}

function fillRect(png, x, y, w, h, r, g, b) {
  for (let py = y; py < Math.min(y + h, png.height); py++) {
    for (let px = x; px < Math.min(x + w, png.width); px++) {
      const idx = (py * png.width + px) * 4;
      png.data[idx] = r;
      png.data[idx + 1] = g;
      png.data[idx + 2] = b;
      png.data[idx + 3] = 255;
    }
  }
}

// --- Design screenshot ---
// Dark status bar (54px) + white header area (38px)
const design = createPNG(WIDTH, HEIGHT);
fillRect(design, 0, 0, WIDTH, STATUS_BAR_HEIGHT, 0, 0, 0); // black status bar
fillRect(design, 0, STATUS_BAR_HEIGHT, WIDTH, HEIGHT - STATUS_BAR_HEIGHT, 255, 255, 255); // white header
// Back button placeholder (gray square)
fillRect(design, 16, 57, 24, 24, 100, 100, 100);
// Title placeholder (dark rectangle centered)
fillRect(design, 120, 62, 153, 16, 30, 30, 30);

fs.writeFileSync(path.join(OUTDIR, 'header-design.png'), PNG.sync.write(design));
console.log('Created: header-design.png');

// --- Good actual (small differences, ~3% diff) ---
const goodActual = createPNG(WIDTH, HEIGHT);
fillRect(goodActual, 0, 0, WIDTH, STATUS_BAR_HEIGHT, 0, 0, 0); // same black status bar
fillRect(goodActual, 0, STATUS_BAR_HEIGHT, WIDTH, HEIGHT - STATUS_BAR_HEIGHT, 255, 255, 255); // same white
// Back button slightly shifted
fillRect(goodActual, 17, 58, 24, 24, 90, 90, 90);
// Title slightly different shade
fillRect(goodActual, 121, 62, 151, 16, 35, 35, 35);

fs.writeFileSync(path.join(OUTDIR, 'header-actual-good.png'), PNG.sync.write(goodActual));
console.log('Created: header-actual-good.png');

// --- Bad actual (very different, ~40% diff) ---
const badActual = createPNG(WIDTH, HEIGHT);
fillRect(badActual, 0, 0, WIDTH, HEIGHT, 245, 245, 245); // all light gray (no status bar distinction)
// Random colored blocks
fillRect(badActual, 10, 10, 80, 30, 255, 0, 0);
fillRect(badActual, 100, 20, 200, 50, 0, 0, 255);
fillRect(badActual, 320, 5, 60, 80, 0, 200, 0);

fs.writeFileSync(path.join(OUTDIR, 'header-actual-bad.png'), PNG.sync.write(badActual));
console.log('Created: header-actual-bad.png');

console.log('\nAll fixtures generated in:', OUTDIR);
