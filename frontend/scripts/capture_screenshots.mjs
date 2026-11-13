/**
 * Capture the reference screenshots for comparison against Design.md.
 *
 * The Phase 2 section also *drives* the booking workflow end to end - find a customer,
 * fill each step, confirm, open the shipment, open the label drawer - so the capture run
 * doubles as a real walkthrough of the primary staff journey rather than a tour of
 * pre-seeded pages.
 *
 * Requires both applications running against the demo database:
 *   backend:  python -m uvicorn app.main:app --port 8000
 *   frontend: npm run dev --prefix frontend        (proxies /api to port 8000)
 *
 * Then, from the repository root:
 *   npm run screenshots --prefix frontend
 *
 * This lives in the frontend package because it uses Playwright, a frontend
 * devDependency; Node resolves imports relative to the script's own location.
 *
 * Output: artifacts/screenshots/*.png (git-ignored; they are review artifacts, not
 * application assets).
 */

import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const BASE = process.env.SCREENSHOT_BASE_URL || 'http://localhost:5173';
const EMAIL = process.env.SCREENSHOT_EMAIL || 'admin@demo.example.com';
const PASSWORD = process.env.SCREENSHOT_PASSWORD || 'SolarisDemo!2026';
const OUT = process.env.SCREENSHOT_OUT_DIR || '../artifacts/screenshots';

// Design.md section 16 reference widths.
const DESKTOP = { width: 1280, height: 800 };
const MOBILE = { width: 375, height: 812 };

async function signIn(page) {
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.getByLabel('Email address').fill(EMAIL);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForSelector('nav[aria-label="Main navigation"]', { timeout: 15000 });
}

async function shot(page, name, { fullPage = true } = {}) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage });
  console.log(`captured ${name}.png`);
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();

  // --- Desktop, 1280 x 800 -------------------------------------------
  const desktop = await browser.newContext({ viewport: DESKTOP, deviceScaleFactor: 1 });
  const page = await desktop.newPage();

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await shot(page, '00-login', { fullPage: false });

  await signIn(page);
  await shot(page, '01-dashboard');

  await page.goto(`${BASE}/customers`, { waitUntil: 'networkidle' });
  await shot(page, '02-customer-list');

  // Create-customer drawer, including the duplicate-candidate review panel.
  await page.getByRole('button', { name: 'Add customer' }).click();
  await page.getByLabel('Full name').fill('Đặng Minh Tuấn');
  await page.getByLabel('Phone number').fill('+1 416 555 0142');
  await page.waitForTimeout(1200);
  await shot(page, '03-create-customer-duplicate-review', { fullPage: false });
  await page.keyboard.press('Escape');

  await page.goto(`${BASE}/customers/1`, { waitUntil: 'networkidle' });
  await shot(page, '04-customer-profile');

  await page.goto(`${BASE}/customers/1?tab=consent`, { waitUntil: 'networkidle' });
  await shot(page, '05-customer-consent');

  await page.goto(`${BASE}/segments`, { waitUntil: 'networkidle' });
  await shot(page, '06-segments');

  await page.goto(`${BASE}/follow-ups`, { waitUntil: 'networkidle' });
  await shot(page, '07-follow-ups');

  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
  await shot(page, '08-settings');

  // --- Phase 2: shipments, booking workflow, detail, labels -----------
  await page.goto(`${BASE}/shipments`, { waitUntil: 'networkidle' });
  await shot(page, '11-shipment-list');

  await page.goto(`${BASE}/shipments?operational_state=exception`, { waitUntil: 'networkidle' });
  await shot(page, '12-shipment-list-exceptions');

  const confirmedId = await runBookingWorkflow(page);

  await page.goto(`${BASE}/shipments/${confirmedId}?tab=tracking`, { waitUntil: 'networkidle' });
  await shot(page, '18-shipment-detail-tracking');

  await page.goto(`${BASE}/shipments/${confirmedId}?tab=details`, { waitUntil: 'networkidle' });
  await shot(page, '19-shipment-detail-details');

  await page.goto(`${BASE}/shipments/${confirmedId}?tab=packages`, { waitUntil: 'networkidle' });
  await shot(page, '20-shipment-detail-packages');

  // The seeded multi-leg shipment carries real legs, carrier references and a partial
  // delivery, so the remaining tabs are captured against it.
  const seeded = await findSeededMultiLegShipment(page);
  await page.goto(`${BASE}/shipments/${seeded}?tab=legs`, { waitUntil: 'networkidle' });
  await shot(page, '21-shipment-detail-legs');
  await page.goto(`${BASE}/shipments/${seeded}?tab=tracking`, { waitUntil: 'networkidle' });
  await shot(page, '22-shipment-detail-partial-delivery');
  await page.goto(`${BASE}/shipments/${seeded}?tab=financials`, { waitUntil: 'networkidle' });
  await shot(page, '23-shipment-detail-financials');

  await page.goto(`${BASE}/shipments/${seeded}?tab=packages`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Print labels' }).first().click();
  await page.waitForSelector('.label-preview', { timeout: 15000 });
  await shot(page, '24-label-preview-drawer', { fullPage: false });
  await page.keyboard.press('Escape');

  await desktop.close();

  // --- Mobile, 375 x 812 ----------------------------------------------
  const mobile = await browser.newContext({ viewport: MOBILE, deviceScaleFactor: 1 });
  const small = await mobile.newPage();
  await signIn(small);
  await small.goto(`${BASE}/customers`, { waitUntil: 'networkidle' });
  await shot(small, '09-customer-list-375');
  await small.goto(`${BASE}/customers/1`, { waitUntil: 'networkidle' });
  await shot(small, '10-customer-profile-375');
  await small.goto(`${BASE}/shipments`, { waitUntil: 'networkidle' });
  await shot(small, '25-shipment-list-375');
  const mobileShipment = await findSeededMultiLegShipment(small);
  await small.goto(`${BASE}/shipments/${mobileShipment}?tab=tracking`, {
    waitUntil: 'networkidle',
  });
  await shot(small, '26-shipment-detail-375');
  await small.goto(`${BASE}/shipments/new`, { waitUntil: 'networkidle' });
  await shot(small, '27-booking-workflow-375');
  await mobile.close();

  await browser.close();
  console.log(`\nScreenshots written to ${OUT}/`);
}

/** Walk the six-step booking workflow for real, capturing each step. */
async function runBookingWorkflow(page) {
  await page.goto(`${BASE}/shipments/new`, { waitUntil: 'networkidle' });

  // Step 1 - customer.
  await page.getByRole('searchbox', { name: /Find a customer/i }).fill('nguyen');
  await page.getByRole('button', { name: /^CUS-/ }).first().click();
  await page.waitForSelector('text=Selected customer');
  await shot(page, '13-booking-step-1-customer');

  // Step 2 - route and service.
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByLabel('Route group').selectOption('CAV');
  await page
    .getByLabel('Contents description')
    .fill('Family gift parcel: clothing and dried fruit (demo)');
  await page.getByLabel('Transport mode').selectOption('air');
  await shot(page, '14-booking-step-2-route');

  // Step 3 - sender and recipient.
  await page.getByRole('button', { name: 'Continue' }).click();
  const sender = page.getByRole('region', { name: 'Sender' });
  await sender.getByLabel('Full name').fill('Solaris Express counter (demo)');
  await sender.getByLabel('Address line 1').fill('4120 Dixie Road, Unit 6');
  await sender.getByLabel('City').fill('Mississauga');
  await sender.getByLabel('Province / state').fill('ON');
  await sender.getByLabel('Country').fill('CA');
  const recipient = page.getByRole('region', { name: 'Recipient' });
  await recipient.getByLabel('Full name').fill('Nguy\u1ec5n Th\u1ecb B\u00edch H\u1ea1nh (demo)');
  await recipient.getByLabel('Address line 1').fill('125 \u0110\u01b0\u1eddng Nguy\u1ec5n Hu\u1ec7');
  await recipient.getByLabel('City').fill('Th\u00e0nh ph\u1ed1 H\u1ed3 Ch\u00ed Minh');
  await recipient.getByLabel('Province / state').fill('H\u1ed3 Ch\u00ed Minh');
  await recipient.getByLabel('Country').fill('VN');
  await shot(page, '15-booking-step-3-contacts');

  // Step 4 - packages: one filled in, then duplicated.
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByLabel('Length').first().fill('45');
  await page.getByLabel('Width').first().fill('35');
  await page.getByLabel('Height').first().fill('25');
  await page.getByLabel('Gross weight').first().fill('6.4');
  await page.getByLabel('Package contents').first().fill('Winter clothing (demo)');
  await page.getByRole('button', { name: 'Duplicate' }).first().click();
  await page.waitForTimeout(300);
  await shot(page, '16-booking-step-4-packages');

  // Step 5 - review, then confirm.
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.waitForSelector('text=Review before confirming');
  await page.getByRole('button', { name: 'Confirm booking' }).click();

  // Step 6 - confirmed: the Solaris ID appears here and nowhere earlier.
  await page.waitForSelector('text=Booking confirmed', { timeout: 20000 });
  await shot(page, '17-booking-step-6-confirmed');

  const href = await page.getByRole('link', { name: 'Open shipment' }).getAttribute('href');
  const shipmentId = href.split('/').pop();
  console.log(`booking workflow confirmed shipment ${shipmentId}`);
  return shipmentId;
}

/** The seeded three-package partially delivered booking, found through the API. */
async function findSeededMultiLegShipment(page) {
  const found = await page.evaluate(async () => {
    const response = await fetch('/api/v1/shipments?operational_state=partially_delivered', {
      credentials: 'same-origin',
    });
    const body = await response.json();
    return body.items?.[0]?.id ?? null;
  });
  if (!found) throw new Error('No partially delivered demo shipment found');
  return found;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
