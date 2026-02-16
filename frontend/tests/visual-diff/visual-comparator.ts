/**
 * Visual Comparator — Design-to-Code POC
 *
 * Three-layer visual verification system for comparing
 * design screenshots against implementation screenshots.
 *
 * Layer 1: Structure validation (DOM tree vs design node tree)
 * Layer 2: Pixel-level comparison (pixelmatch)
 * Layer 3: AI semantic comparison (Claude Vision)
 *
 * Threshold strategy:
 *   < 5% pixel diff  → PASS
 *   5-15% pixel diff  → escalate to Layer 3 (AI judgment)
 *   > 15% pixel diff  → FAIL (auto-retry)
 *
 * Smoke test calibration:
 *   Components 1-3: run all three layers (calibrate baseline)
 *   Components 4+:  run Layer 1 + Layer 2 only (save cost)
 *   Full page:       run all three layers (final gate)
 *
 * Author: browser-tester
 * Date: 2026-02-14
 */

import type { Page } from '@playwright/test';

// --- Types ---

export interface VisualDiffResult {
  /** Which component was compared */
  componentId: string;
  /** Layer 1: structure validation result */
  structureCheck: StructureCheckResult;
  /** Layer 2: pixel diff result */
  pixelDiff: PixelDiffResult;
  /** Layer 3: AI semantic comparison (optional, only for smoke test or escalation) */
  aiComparison?: AIComparisonResult;
  /** Overall verdict */
  verdict: 'pass' | 'needs_review' | 'fail';
  /** Timestamp */
  timestamp: string;
}

export interface StructureCheckResult {
  passed: boolean;
  /** Number of expected elements vs actual */
  expectedElementCount: number;
  actualElementCount: number;
  /** Layout direction matches (flex-row vs flex-col, grid, etc.) */
  layoutMatch: boolean;
  /** Missing element selectors */
  missingElements: string[];
  /** Extra unexpected elements */
  extraElements: string[];
}

export interface PixelDiffResult {
  /** Percentage of differing pixels (0-100) */
  diffPercentage: number;
  /** Total pixels compared */
  totalPixels: number;
  /** Number of differing pixels */
  diffPixels: number;
  /** Path to the diff image (highlighted differences) */
  diffImagePath?: string;
  /** Path to the implementation screenshot */
  actualImagePath: string;
  /** Path to the design reference screenshot */
  expectedImagePath: string;
}

export interface AIComparisonResult {
  /** AI's overall judgment */
  verdict: 'match' | 'minor_differences' | 'significant_differences';
  /** Detailed differences found */
  differences: AIDetectedDifference[];
  /** AI confidence score (0-1) */
  confidence: number;
  /** Raw AI response text */
  rawResponse: string;
}

export interface AIDetectedDifference {
  severity: 'low' | 'medium' | 'high';
  area: string;
  description: string;
}

export interface CompareOptions {
  /** Component identifier for reporting */
  componentId: string;
  /** CSS selector to screenshot in the implementation */
  selector: string;
  /** Path to the design reference image */
  designScreenshotPath: string;
  /** Whether to run Layer 3 (AI comparison) */
  runAIComparison: boolean;
  /** Pixel diff threshold for auto-pass (default: 5) */
  passThreshold?: number;
  /** Pixel diff threshold for auto-fail (default: 15) */
  failThreshold?: number;
  /** Viewport size for screenshot (default: { width: 1440, height: 900 }) */
  viewport?: { width: number; height: number };
}

// --- Thresholds ---

const DEFAULT_PASS_THRESHOLD = 5; // < 5% diff = pass
const DEFAULT_FAIL_THRESHOLD = 15; // > 15% diff = fail (no AI needed)

// --- Layer 1: Structure Validation ---

/**
 * Compare DOM structure against expected design structure.
 *
 * Checks:
 * - Element count matches
 * - Layout direction (flex-row/flex-col/grid) matches
 * - Key child elements are present
 */
export async function checkStructure(
  page: Page,
  selector: string,
  expectedStructure: {
    elementCount: number;
    layoutDirection?: 'row' | 'column' | 'grid';
    requiredChildren?: string[];
  }
): Promise<StructureCheckResult> {
  const container = page.locator(selector);

  // Count direct children
  const children = container.locator(':scope > *');
  const actualCount = await children.count();

  // Check layout direction
  let layoutMatch = true;
  if (expectedStructure.layoutDirection) {
    const style = await container.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        display: computed.display,
        flexDirection: computed.flexDirection,
      };
    });

    if (expectedStructure.layoutDirection === 'grid') {
      layoutMatch = style.display === 'grid';
    } else {
      layoutMatch =
        style.display === 'flex' &&
        style.flexDirection === expectedStructure.layoutDirection;
    }
  }

  // Check required children
  const missingElements: string[] = [];
  const extraElements: string[] = [];
  if (expectedStructure.requiredChildren) {
    for (const childSelector of expectedStructure.requiredChildren) {
      const child = container.locator(childSelector);
      if ((await child.count()) === 0) {
        missingElements.push(childSelector);
      }
    }
  }

  return {
    passed:
      missingElements.length === 0 &&
      layoutMatch &&
      Math.abs(actualCount - expectedStructure.elementCount) <= 2,
    expectedElementCount: expectedStructure.elementCount,
    actualElementCount: actualCount,
    layoutMatch,
    missingElements,
    extraElements,
  };
}

// --- Image Resize Helper ---

/**
 * Nearest-neighbor resize for PNG images.
 * Used to align design screenshots (possibly 2x retina) with implementation screenshots.
 * No external dependency — uses pngjs data directly.
 */
function resizePNG(
  src: { data: Buffer; width: number; height: number },
  targetWidth: number,
  targetHeight: number
): { data: Buffer; width: number; height: number } {
  const dst = Buffer.alloc(targetWidth * targetHeight * 4);
  const xRatio = src.width / targetWidth;
  const yRatio = src.height / targetHeight;

  for (let y = 0; y < targetHeight; y++) {
    for (let x = 0; x < targetWidth; x++) {
      const srcX = Math.floor(x * xRatio);
      const srcY = Math.floor(y * yRatio);
      const srcIdx = (srcY * src.width + srcX) * 4;
      const dstIdx = (y * targetWidth + x) * 4;
      dst[dstIdx] = src.data[srcIdx];
      dst[dstIdx + 1] = src.data[srcIdx + 1];
      dst[dstIdx + 2] = src.data[srcIdx + 2];
      dst[dstIdx + 3] = src.data[srcIdx + 3];
    }
  }

  return { data: dst, width: targetWidth, height: targetHeight };
}

// --- Layer 2: Pixel Diff ---

/**
 * Take a screenshot of a component and compare against design reference.
 *
 * Uses pixelmatch for pixel-level comparison.
 * Returns diff percentage and generates a diff highlight image.
 *
 * Prerequisites: npm install pixelmatch pngjs
 */
export async function comparePixels(
  page: Page,
  selector: string,
  designScreenshotPath: string,
  outputDir: string
): Promise<PixelDiffResult> {
  // Take implementation screenshot
  const element = page.locator(selector);
  const actualBuffer = await element.screenshot();
  const actualImagePath = `${outputDir}/actual.png`;

  // Dynamic imports for pixelmatch + pngjs (Node.js modules)
  const fs = await import('fs');
  const { PNG } = await import('pngjs');
  const pixelmatch = (await import('pixelmatch')).default;

  // Save actual screenshot
  fs.writeFileSync(actualImagePath, actualBuffer);

  // Load design reference
  const expectedBuffer = fs.readFileSync(designScreenshotPath);
  const expected = PNG.sync.read(expectedBuffer);
  const actual = PNG.sync.read(actualBuffer);

  // Resize if dimensions don't match (design may be 2x retina export)
  if (expected.width !== actual.width || expected.height !== actual.height) {
    console.warn(
      `Size mismatch: design=${expected.width}x${expected.height}, actual=${actual.width}x${actual.height}. Resizing design to match.`
    );
    // Nearest-neighbor downscale using pngjs (no extra dependency)
    const resized = resizePNG(expected, actual.width, actual.height);
    expected.data = resized.data;
    expected.width = resized.width;
    expected.height = resized.height;
  }

  // Create diff image
  const { width, height } = expected;
  const diff = new PNG({ width, height });
  const diffPixels = pixelmatch(
    expected.data,
    actual.data,
    diff.data,
    width,
    height,
    { threshold: 0.1 } // Sensitivity: 0.1 = moderate tolerance for anti-aliasing
  );

  // Save diff image
  const diffImagePath = `${outputDir}/diff.png`;
  fs.writeFileSync(diffImagePath, PNG.sync.write(diff));

  const totalPixels = width * height;
  const diffPercentage = (diffPixels / totalPixels) * 100;

  return {
    diffPercentage: Math.round(diffPercentage * 100) / 100,
    totalPixels,
    diffPixels,
    diffImagePath,
    actualImagePath,
    expectedImagePath: designScreenshotPath,
  };
}

// --- Layer 3: AI Semantic Comparison ---

/**
 * Claude Vision comparison prompt template.
 *
 * Sends design screenshot + implementation screenshot to Claude
 * and asks for structured difference analysis.
 *
 * For POC: This is a prompt template. Actual API call integration
 * will be done when connecting to the backend pipeline.
 */
export function buildAIComparisonPrompt(
  componentName: string
): string {
  return `You are a UI design review expert. Compare these two images:

Image 1 (DESIGN): The original design mockup for the "${componentName}" component.
Image 2 (IMPLEMENTATION): The actual rendered implementation in a browser.

Analyze the visual differences and respond in this exact JSON format:
{
  "verdict": "match" | "minor_differences" | "significant_differences",
  "confidence": 0.0-1.0,
  "differences": [
    {
      "severity": "low" | "medium" | "high",
      "area": "description of the affected area",
      "description": "what is different"
    }
  ],
  "summary": "one sentence overall assessment"
}

Evaluation criteria:
- "match": Implementation looks visually identical to the design. Minor anti-aliasing or sub-pixel differences are acceptable.
- "minor_differences": Small deviations (slightly different spacing, font rendering differences, minor color shade differences). These are acceptable and do NOT require a retry.
- "significant_differences": Visible layout errors, wrong colors, missing elements, incorrect typography, or broken alignment. These REQUIRE a retry.

Focus on:
1. Layout structure (element positions, alignment, spacing)
2. Colors (background, text, borders — compare actual hex values if visible)
3. Typography (font size, weight, line height)
4. Spacing (padding, margins, gaps between elements)
5. Visual hierarchy (element prominence, contrast)

Ignore:
- Anti-aliasing differences
- Sub-pixel rendering variations
- Cursor/selection state differences
- Scrollbar appearance`;
}

/**
 * Parse Claude Vision API response into structured result.
 *
 * For POC: accepts raw JSON string from Claude.
 */
export function parseAIResponse(rawResponse: string): AIComparisonResult {
  try {
    // Extract JSON from response (Claude may wrap it in markdown code blocks)
    const jsonMatch = rawResponse.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return {
        verdict: 'significant_differences',
        differences: [],
        confidence: 0,
        rawResponse,
      };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    return {
      verdict: parsed.verdict || 'significant_differences',
      differences: (parsed.differences || []).map((d: any) => ({
        severity: d.severity || 'medium',
        area: d.area || 'unknown',
        description: d.description || '',
      })),
      confidence: parsed.confidence || 0,
      rawResponse,
    };
  } catch {
    return {
      verdict: 'significant_differences',
      differences: [],
      confidence: 0,
      rawResponse,
    };
  }
}

// --- Orchestrator ---

/**
 * Run the full visual comparison pipeline for a single component.
 *
 * Implements the three-layer verification with threshold-based escalation:
 * 1. Always run Layer 1 (structure)
 * 2. Always run Layer 2 (pixel diff)
 * 3. Run Layer 3 (AI) only if:
 *    - options.runAIComparison is true (smoke test components 1-3, full page)
 *    - OR pixel diff is in the 5-15% "gray zone"
 */
export async function compareComponent(
  page: Page,
  options: CompareOptions,
  expectedStructure?: {
    elementCount: number;
    layoutDirection?: 'row' | 'column' | 'grid';
    requiredChildren?: string[];
  }
): Promise<VisualDiffResult> {
  const passThreshold = options.passThreshold ?? DEFAULT_PASS_THRESHOLD;
  const failThreshold = options.failThreshold ?? DEFAULT_FAIL_THRESHOLD;
  const outputDir = `test-results/visual-diff/${options.componentId}`;

  // Ensure output directory exists
  const fs = await import('fs');
  fs.mkdirSync(outputDir, { recursive: true });

  // Set viewport if specified
  if (options.viewport) {
    await page.setViewportSize(options.viewport);
  }

  // Layer 1: Structure check (if expected structure provided)
  let structureCheck: StructureCheckResult = {
    passed: true,
    expectedElementCount: 0,
    actualElementCount: 0,
    layoutMatch: true,
    missingElements: [],
    extraElements: [],
  };
  if (expectedStructure) {
    structureCheck = await checkStructure(
      page,
      options.selector,
      expectedStructure
    );
  }

  // Layer 2: Pixel diff
  const pixelDiff = await comparePixels(
    page,
    options.selector,
    options.designScreenshotPath,
    outputDir
  );

  // Determine if Layer 3 is needed
  let aiComparison: AIComparisonResult | undefined;
  const inGrayZone =
    pixelDiff.diffPercentage >= passThreshold &&
    pixelDiff.diffPercentage <= failThreshold;

  if (options.runAIComparison || inGrayZone) {
    // Layer 3: AI comparison
    // For POC, this will be called externally via backend API
    // Here we just prepare the prompt and placeholder
    const _prompt = buildAIComparisonPrompt(options.componentId);
    // TODO: Integrate with backend Claude Vision API call
    // aiComparison = await callClaudeVision(prompt, designPath, actualPath);
  }

  // Determine overall verdict
  let verdict: VisualDiffResult['verdict'];
  if (!structureCheck.passed) {
    verdict = 'fail';
  } else if (pixelDiff.diffPercentage < passThreshold) {
    verdict = 'pass';
  } else if (pixelDiff.diffPercentage > failThreshold) {
    verdict = 'fail';
  } else if (aiComparison) {
    verdict =
      aiComparison.verdict === 'significant_differences'
        ? 'fail'
        : aiComparison.verdict === 'minor_differences'
          ? 'needs_review'
          : 'pass';
  } else {
    verdict = 'needs_review';
  }

  return {
    componentId: options.componentId,
    structureCheck,
    pixelDiff,
    aiComparison,
    verdict,
    timestamp: new Date().toISOString(),
  };
}

// --- SSE Event Format ---

/**
 * Format a VisualDiffResult for SSE push to frontend.
 *
 * This matches the existing ActivityFeed event format
 * so it can be rendered in the PipelineBar.
 */
export function formatForSSE(result: VisualDiffResult): object {
  return {
    type: 'visual_diff',
    component_id: result.componentId,
    verdict: result.verdict,
    pixel_diff_percentage: result.pixelDiff.diffPercentage,
    structure_passed: result.structureCheck.passed,
    ai_verdict: result.aiComparison?.verdict ?? null,
    diff_image: result.pixelDiff.diffImagePath ?? null,
    timestamp: result.timestamp,
  };
}

// --- CLI Entry Point ---

/**
 * CLI interface for subprocess calls from Python backend.
 *
 * Usage:
 *   npx ts-node tests/visual-diff/visual-comparator.ts compare \
 *     --design /path/to/design.png \
 *     --actual /path/to/actual.png \
 *     --output /path/to/output-dir \
 *     --component-id sidebar
 *
 * Output: JSON to stdout (PixelDiffResult)
 *
 * This allows VisualDiffNode (Python) to call pixel diff
 * without needing a running Playwright browser — it compares
 * two pre-existing PNG files directly.
 */
async function compareFilesCLI(args: string[]): Promise<void> {
  const flags: Record<string, string> = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i].replace(/^--/, '');
    flags[key] = args[i + 1];
  }

  if (!flags['design'] || !flags['actual']) {
    console.error(
      'Usage: compare --design <path> --actual <path> [--output <dir>] [--component-id <id>]'
    );
    process.exit(1);
  }

  const fs = await import('fs');
  const { PNG } = await import('pngjs');
  const pixelmatch = (await import('pixelmatch')).default;

  const outputDir = flags['output'] || 'test-results/visual-diff/cli';
  const componentId = flags['component-id'] || 'unknown';
  fs.mkdirSync(outputDir, { recursive: true });

  // Load both images
  const expectedBuffer = fs.readFileSync(flags['design']);
  const actualBuffer = fs.readFileSync(flags['actual']);
  const expected = PNG.sync.read(expectedBuffer);
  const actual = PNG.sync.read(actualBuffer);

  // Resize if needed
  let expData = expected;
  if (expected.width !== actual.width || expected.height !== actual.height) {
    const resized = resizePNG(expected, actual.width, actual.height);
    expData = { ...expected, ...resized } as any;
  }

  const { width, height } = actual;
  const diff = new PNG({ width, height });
  const diffPixels = pixelmatch(
    expData.data,
    actual.data,
    diff.data,
    width,
    height,
    { threshold: 0.1 }
  );

  const diffImagePath = `${outputDir}/diff.png`;
  fs.writeFileSync(diffImagePath, PNG.sync.write(diff));

  const totalPixels = width * height;
  const diffPercentage = Math.round((diffPixels / totalPixels) * 10000) / 100;

  const result: PixelDiffResult = {
    diffPercentage,
    totalPixels,
    diffPixels,
    diffImagePath,
    actualImagePath: flags['actual'],
    expectedImagePath: flags['design'],
  };

  // Determine verdict using thresholds
  let verdict: 'pass' | 'needs_review' | 'fail';
  if (diffPercentage < DEFAULT_PASS_THRESHOLD) {
    verdict = 'pass';
  } else if (diffPercentage > DEFAULT_FAIL_THRESHOLD) {
    verdict = 'fail';
  } else {
    verdict = 'needs_review';
  }

  // Output JSON to stdout for Python backend to parse
  console.log(
    JSON.stringify({
      component_id: componentId,
      verdict,
      pixel_diff: result,
      timestamp: new Date().toISOString(),
    })
  );
}

// CLI dispatch
const cliArgs = process.argv.slice(2);
if (cliArgs[0] === 'compare') {
  compareFilesCLI(cliArgs.slice(1)).catch((err) => {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  });
}
