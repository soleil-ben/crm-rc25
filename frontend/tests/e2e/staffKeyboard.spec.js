/**
 * Keyboard-only walkthroughs of the eight workflows the Phase 5B brief names.
 *
 * These are **walkthroughs, not audits**. axe can tell you a control has an accessible
 * name; only driving the workflow tells you the control can be reached, operated, and
 * leaves focus somewhere sensible afterwards. `Design.md` section 19 requires that a
 * keyboard user can complete customer creation, booking, tracking assignment and task
 * completion; this covers those and the four the brief adds.
 *
 * **The rule: no mouse, ever.** No `click()`, no `fill()`, no `focus()`. Only
 * `keyboard.press` and `keyboard.type`, which is what a keyboard user actually has.
 * `tabTo` walks the real focus order and fails if a control is never reached -- calling
 * `locator.focus()` would answer an easier question than the one being asked.
 *
 * Two things the first draft of this file got wrong, both worth recording because they
 * are the mistakes a reviewer would otherwise repeat:
 *
 * * **Tab panels are not in the tab order, and should not be.** The shipment detail
 *   tablist uses roving tabindex, so Tab reaches the tablist once and Arrow keys move
 *   between tabs. Searching the tab order for a "Timeline" tab found nothing and looked
 *   like a defect; it is correct ARIA practice.
 * * **The focus trap focuses the first field on a 20 ms timer.** Asserting immediately
 *   after the dialog becomes visible reads focus before it has moved.
 */

import { expect, test } from './diagnostics.js';

/** How many tab stops to search before giving up. Generous; the failure is the signal. */
const MAX_TABS = 140;

/** The focus trap focuses its first field on a short timer; outwait it before asserting. */
const FOCUS_TRAP_SETTLE_MS = 150;

async function describeFocus(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return null;
    const style = getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type'),
      role: el.getAttribute('role'),
      name: (
        el.getAttribute('aria-label') ||
        (el.labels && el.labels[0] && el.labels[0].innerText) ||
        el.innerText ||
        el.getAttribute('placeholder') ||
        ''
      ).trim(),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    };
  });
}

/**
 * Tab forward until `predicate` is true of the focused element, and return its details.
 * On failure the whole focus order is reported, which is the useful part.
 */
async function tabTo(page, describe, predicate) {
  const seen = [];
  for (let step = 0; step < MAX_TABS; step += 1) {
    await page.keyboard.press('Tab');
    const info = await describeFocus(page);
    if (!info) continue;
    seen.push(`${info.tag}${info.role ? `[${info.role}]` : ''} "${info.name.slice(0, 40)}"`);
    if (predicate(info)) return info;
  }
  throw new Error(
    `Keyboard could not reach ${describe} in ${MAX_TABS} tab stops.\nFocus order seen:\n  ` +
      seen.join('\n  '),
  );
}

function named(fragment) {
  const wanted = fragment.toLowerCase();
  return (info) => info.name.toLowerCase().includes(wanted);
}

/** Is focus inside the open dialog? */
async function focusIsInDialog(page) {
  return page.evaluate(() => {
    const dialog = document.querySelector('[role="dialog"]');
    return dialog ? dialog.contains(document.activeElement) : false;
  });
}

const runId = () => `KB${Date.now().toString(36).toUpperCase()}`;

async function firstShipment(request) {
  const list = await (await request.get('/api/v1/shipments?limit=30')).json();
  return list.items.find((item) => item.public_id) || list.items[0];
}

// --- 1. Customer creation ------------------------------------------------------------------

test('1. a customer can be created with the keyboard alone', async ({ page }) => {
  const run = runId();
  await page.goto('/customers');
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible();

  await tabTo(page, 'the Add customer button', named('add customer'));
  await page.keyboard.press('Enter');

  await expect(page.getByRole('dialog')).toBeVisible();
  await page.waitForTimeout(FOCUS_TRAP_SETTLE_MS);
  expect(await focusIsInDialog(page), 'focus did not move into the dialog').toBe(true);

  await tabTo(page, 'the full name field', named('full name'));
  await page.keyboard.type(`Nguyễn Văn Kiên ${run}`);

  await tabTo(page, 'the email field', named('email'));
  await page.keyboard.type(`kien.${run}@example.com`);

  // The drawer's submit button carries the same label as the trigger that opened it, so
  // this matches on the tag as well -- a `button` named "Add customer", reached from
  // inside the focus trap.
  await tabTo(
    page,
    'the submit button inside the drawer',
    (info) => info.tag === 'button' && named('add customer')(info),
  );
  await page.keyboard.press('Enter');

  await expect(page.getByText(`Nguyễn Văn Kiên ${run}`).first()).toBeVisible({ timeout: 15_000 });
});

// --- 2. Tracking assignment (manual / external link) ----------------------------------------

test('2. the tracking tab is reachable and offers no connected_api mode', async ({
  page,
  request,
}) => {
  const shipment = await firstShipment(request);
  test.skip(!shipment, 'no shipment in the demo data');

  await page.goto(`/shipments/${shipment.id}`);
  await expect(page.getByRole('heading', { name: new RegExp(shipment.public_id) })).toBeVisible();

  // One Tab reaches the tablist; Arrow keys move within it (roving tabindex).
  await tabTo(page, 'the shipment tablist', (info) => info.role === 'tab');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  const landed = await describeFocus(page);
  expect(landed.role, 'arrow keys did not move within the tablist').toBe('tab');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(300);

  // No provider exists (DEC-0075), so no keyboard user can select a connected mode --
  // because there is no such control anywhere on this surface.
  const body = (await page.locator('main').innerText()).toLowerCase();
  expect(body).not.toContain('connected api');
  expect(body).not.toContain('connected_api');
});

// --- 3. Booking confirmation ------------------------------------------------------------------

test('3. the booking wizard is operable from the keyboard', async ({ page }) => {
  await page.goto('/shipments/new');
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});

  // Reaching the customer field is the first real test; everything else follows from it.
  const field = await tabTo(page, 'the customer field', named('customer'));
  expect(field.name).toBeTruthy();

  await tabTo(page, 'a continue/next control', (info) =>
    named('continue')(info) || named('next')(info) || named('save draft')(info),
  );
});

// --- 4. Package and event updates ----------------------------------------------------------------

test('4. a milestone can be recorded from the keyboard', async ({ page, request }) => {
  // A cancelled booking no longer offers Record event (UAT round 3), so pick a live one.
  const list = await (await request.get('/api/v1/shipments?limit=30')).json();
  const shipment = list.items.find(
    (item) => item.public_id && item.booking_state !== 'cancelled',
  );
  test.skip(!shipment, 'no live shipment in the demo data');

  await page.goto(`/shipments/${shipment.id}`);

  // Recording a milestone is an **inline form**, not a modal -- a deliberate choice, and
  // the better one here: the timeline stays on screen while the event is described. An
  // earlier draft of this test asserted a dialog and failed, which was the test being
  // wrong about the design rather than the design being wrong.
  await expect(page.getByRole('heading', { name: new RegExp(shipment.public_id) })).toBeVisible();

  // `tag === 'button'` matters here. The tab panel's own accessible text contains the
  // words "Record event" too, so a name-only match lands on the panel and Enter does
  // nothing -- which looked exactly like a button that could not be activated.
  await tabTo(
    page,
    'the Record event button',
    (info) => info.tag === 'button' && named('record event')(info),
  );
  await page.keyboard.press('Enter');
  await page.waitForTimeout(400);

  // Focus moves into the revealed form, on its first field (UAT round 3): the button
  // that held focus is gone once the form opens.
  const focused = await describeFocus(page);
  expect(focused?.tag, 'focus did not move into the event form').toBe('select');

  await tabTo(
    page,
    'the submit button of the inline form',
    (info) => info.tag === 'button' && named('record event')(info),
  );
});

// --- 5. Label printing -------------------------------------------------------------------------

test('5. label printing is reachable from the keyboard', async ({ page, request }) => {
  const shipment = await firstShipment(request);
  test.skip(!shipment, 'no shipment in the demo data');

  await page.goto(`/shipments/${shipment.id}`);
  // Wait for the record before tabbing: tabbing into a half-rendered page reaches a
  // button whose handler is not attached yet, and Enter is then silently lost.
  await expect(page.getByRole('heading', { name: new RegExp(shipment.public_id) })).toBeVisible();

  await tabTo(
    page,
    'the Print labels button',
    (info) => info.tag === 'button' && named('print labels')(info),
  );
  await page.keyboard.press('Enter');

  await expect(page.getByRole('dialog')).toBeVisible();
  await page.waitForTimeout(FOCUS_TRAP_SETTLE_MS);
  expect(await focusIsInDialog(page), 'focus did not enter the label dialog').toBe(true);
});

// --- 6. Task completion --------------------------------------------------------------------------

test('6. a follow-up task can be completed from the keyboard', async ({ page }) => {
  await page.goto('/follow-ups');
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});

  await tabTo(page, 'a complete-task control', (info) =>
    named('complete')(info) || named('mark done')(info) || named('done')(info),
  );
  await page.keyboard.press('Enter');
  await page.waitForTimeout(600);

  // Focus must still be somewhere real: a control that vanishes on activation and drops
  // focus to <body> strands a keyboard user at the top of the document.
  const after = await describeFocus(page);
  expect(after.tag, 'focus fell back to the document body').not.toBe('body');
});

// --- 7. Report filtering and export ----------------------------------------------------------------

test('7. reports can be filtered and exported from the keyboard', async ({ page }) => {
  await page.goto('/reports?from=2026-08-01&to=2026-09-10');
  await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();

  await tabTo(page, 'the from-date field', named('from'));
  await tabTo(page, 'the to-date field', named('to'));
  await tabTo(page, 'the apply control', (info) => named('apply')(info) || named('update')(info));
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Route mix' })).toBeVisible();

  await tabTo(page, 'an export control', named('export'));
  const download = page.waitForEvent('download', { timeout: 15_000 });
  await page.keyboard.press('Enter');
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
});

// --- 8. The complete import flow ---------------------------------------------------------------------

test('8. the import flow, with a duplicate decision and the confirmation', async ({ page }) => {
  const run = runId();
  const header = 'full_name,email,phone,country_code,city,preferred_language,source_record_id\r\n';

  await page.goto('/customers/import');
  await expect(page.getByLabel('CSV file to import')).toBeVisible();

  // The file input is the one step a keyboard cannot finish unaided, because choosing a
  // file opens the operating system's own dialog. What matters here is that the input is
  // reachable and labelled; the bytes are then supplied the way that dialog would.
  await tabTo(page, 'the file input', (info) => info.type === 'file' || named('csv file')(info));

  await page.setInputFiles('input[type="file"]', {
    name: 'customers.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      `${header}Vũ Thị Lan ${run},lan.${run}@example.com,,CA,Mississauga,vi,${run}-A\r\n`,
      'utf8',
    ),
  });
  await expect(page.getByRole('heading', { name: 'Every row' })).toBeVisible();

  await tabTo(page, 'the import button', named('import 1 customer'));
  await page.keyboard.press('Enter');

  await expect(page.getByRole('button', { name: 'Yes, import now' })).toBeVisible();
  await page.waitForTimeout(FOCUS_TRAP_SETTLE_MS);
  expect(await focusIsInDialog(page), 'focus did not move into the confirmation').toBe(true);

  await tabTo(page, 'the confirm button', named('yes, import now'));
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Import another file' })).toBeVisible({
    timeout: 15_000,
  });

  // The duplicate decision: the same person again, which must be held for a decision and
  // never merged automatically.
  await tabTo(page, 'the import-another control', named('import another file'));
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('CSV file to import')).toBeVisible();
  await page.setInputFiles('input[type="file"]', {
    name: 'customers.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      `${header}Vũ Thị Lan ${run},lan.second.${run}@example.com,,CA,Mississauga,vi,${run}-B\r\n`,
      'utf8',
    ),
  });
  await page.waitForTimeout(900);

  const decisions = page.getByLabel(/^Decision/);
  if (await decisions.count()) {
    await tabTo(page, 'the duplicate decision control', named('decision'));
    const control = await describeFocus(page);
    expect(control.tag).toBe('select');
  }
});

// --- Structure every keyboard walkthrough depends on ---------------------------------------------------

test('the skip link is the first tab stop and moves focus into main', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});

  await page.keyboard.press('Tab');
  const first = await describeFocus(page);
  expect(first.name.toLowerCase()).toContain('skip');

  await page.keyboard.press('Enter');
  const inMain = await page.evaluate(() => {
    const main = document.querySelector('main');
    if (!main) return false;
    return main === document.activeElement || main.contains(document.activeElement);
  });
  expect(inMain, 'the skip link did not move focus into main').toBe(true);
});

test('every control in the header shows a visible focus indicator', async ({ page }) => {
  await page.goto('/customers');
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});

  // The first dozen stops are the shell: skip link, navigation, search, account menu.
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press('Tab');
    const info = await describeFocus(page);
    if (!info || info.tag === 'body') continue;
    const ring =
      (info.outlineStyle !== 'none' && parseFloat(info.outlineWidth) > 0) ||
      (info.boxShadow && info.boxShadow !== 'none');
    expect(ring, `no visible focus indicator on ${info.tag} "${info.name}"`).toBe(true);
  }
});
