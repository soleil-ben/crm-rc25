/**
 * Capture the public tracking screenshots for review against Design.md.
 *
 * Separate from `capture_screenshots.mjs`, which drives the staff workflow, and separate
 * again from the Playwright assertion suite in `tests/e2e/`. This script only looks; it
 * asserts nothing. Screenshots are review artifacts, not tests (DEC-0029).
 *
 * Both languages are captured for every state, because a Vietnamese page is not an
 * English page with different words in it -- the text runs about 30% longer and the
 * layout has to absorb that (`Design.md` section 15).
 *
 * Requires both applications running against the demo database:
 *   backend:  backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000 \
 *               --app-dir backend --no-proxy-headers
 *   frontend: npm run dev --prefix frontend
 *
 * Then, from the repository root:
 *   node frontend/scripts/capture_public_screenshots.mjs
 *
 * Output: artifacts/screenshots/public-*.png (git-ignored).
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, '..');
const REPO_ROOT = resolve(FRONTEND, '..');

const BASE = process.env.SCREENSHOT_BASE_URL || 'http://localhost:5173';
const OUT = process.env.SCREENSHOT_OUT_DIR || join(REPO_ROOT, 'artifacts', 'screenshots');

/** Design.md section 16's reference widths. */
const VIEWPORTS = {
  mobile: { width: 375, height: 812 },
  tablet: { width: 768, height: 1024 },
  laptop: { width: 1280, height: 800 },
  desktop: { width: 1440, height: 900 },
  wide: { width: 1920, height: 1080 },
};

const LANGUAGES = ['en', 'vi'];

function seedReferences() {
  const python = join(REPO_ROOT, 'backend', '.venv', 'Scripts', 'python.exe');
  const script = `
import json, sys
sys.path.insert(0, "backend")
from sqlalchemy import text
from app.core.config import settings
from app.core.db import build_engine

engine = build_engine(settings.database_url)
with engine.connect() as connection:
    def one(sql):
        row = connection.execute(text(sql)).fetchone()
        return row[0] if row else None
    out = {}
    out["partial"] = one("""
        SELECT s.public_id FROM shipments s
        WHERE s.operational_state = 'partially_delivered' AND s.booking_state = 'confirmed'
        ORDER BY s.id LIMIT 1
    """)
    out["package"] = one(f"""
        SELECT p.package_reference FROM shipment_packages p
        JOIN shipments s ON s.id = p.shipment_id
        WHERE s.public_id = '{out["partial"]}' AND p.sequence = 2
    """)
    out["exception"] = one("""
        SELECT public_id FROM shipments
        WHERE operational_state = 'exception' AND booking_state = 'confirmed'
        ORDER BY id LIMIT 1
    """)
    out["cancelled"] = one("""
        SELECT public_id FROM shipments
        WHERE booking_state = 'cancelled' AND public_id IS NOT NULL ORDER BY id LIMIT 1
    """)
print(json.dumps(out))
`;
  const stdout = execFileSync(python, ['-c', script], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  return JSON.parse(stdout.trim().split('\n').pop());
}

/** Set the stored language before the app boots, so no switch is captured mid-flight. */
async function newPage(browser, viewport, language) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript((lang) => {
    try {
      window.localStorage.setItem('solaris.public.language', lang);
    } catch {
      /* storage may be unavailable; the page copes */
    }
  }, language);
  return { context, page: await context.newPage() };
}

async function shot(page, name) {
  // Wait for the page to have settled into one of its states rather than for the network
  // to go idle: a failed lookup leaves Playwright's network accounting busy, and the
  // error screen is precisely one of the states worth photographing.
  await page
    .locator('.public-card, .public-result, .public-demo-banner')
    .first()
    .waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, `${name}.png`), fullPage: true });
  console.log(`captured ${name}.png`);
}

/** Fill the rate-limit window so the limited state can be photographed. */
async function exhaustLimiter(page) {
  await page.evaluate(async () => {
    for (let batch = 0; batch < 20; batch += 1) {
      const responses = await Promise.all(
        Array.from({ length: 25 }, () =>
          fetch('/api/v1/public/track/SX-CAV-ABCDEFGHJKLM', { credentials: 'omit' }),
        ),
      );
      if (responses.some((response) => response.status === 429)) {
        // One more burst, so the whole window is full of fresh hits.
        await Promise.all(
          Array.from({ length: 25 }, () =>
            fetch('/api/v1/public/track/SX-CAV-ABCDEFGHJKLM', { credentials: 'omit' }),
          ),
        );
        return;
      }
    }
  });
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const references = seedReferences();
  console.log('using demo references:', references);

  const browser = await chromium.launch();

  // --- Every state, both languages, at the phone width ------------------
  for (const language of LANGUAGES) {
    const { context, page } = await newPage(browser, VIEWPORTS.mobile, language);

    await page.goto(`${BASE}/track`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-01-landing-375`);

    await page.goto(`${BASE}/track/${references.partial}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-02-result-375`);

    await page.goto(`${BASE}/track/${references.package}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-03-package-375`);

    await page.goto(`${BASE}/track/${references.exception}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-04-exception-375`);

    await page.goto(`${BASE}/track/${references.cancelled}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-05-cancelled-375`);

    await page.goto(`${BASE}/track/SX-CAV-ABCDEFGHJKLM`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-06-unknown-375`);

    await context.close();
  }

  // --- The result at every reference width -------------------------------
  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    const { context, page } = await newPage(browser, viewport, 'en');
    await page.goto(`${BASE}/track/${references.partial}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-widths-${viewport.width}x${viewport.height}-${name}`);
    await context.close();
  }

  // The longer language at the tightest width is the case worth a second look.
  {
    const { context, page } = await newPage(browser, VIEWPORTS.mobile, 'vi');
    await page.goto(`${BASE}/track/${references.partial}`, { waitUntil: 'domcontentloaded' });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    console.log(`Vietnamese horizontal overflow at 375 px: ${overflow}px`);
    await context.close();
  }

  // --- The rate-limited state, captured last -----------------------------
  // Last on purpose: it leaves the limiter full for about a minute.
  for (const language of LANGUAGES) {
    const { context, page } = await newPage(browser, VIEWPORTS.mobile, language);
    await page.goto(`${BASE}/track`, { waitUntil: 'domcontentloaded' });
    await exhaustLimiter(page);
    await page.goto(`${BASE}/track/${references.partial}`, { waitUntil: 'domcontentloaded' });
    await shot(page, `public-${language}-07-rate-limited-375`);
    await context.close();
  }

  await browser.close();
  console.log(`\nWrote screenshots to ${OUT}`);
  console.log('The rate limiter was deliberately exhausted; give it a minute before re-running.');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
