/**
 * Shared steps for the Phase 14 workspace specs: a new HCM air master through the screens,
 * and a member added through the screens' search.
 *
 * `pickFreeShipment` reads (never writes) the scratch database for a confirmed Vietnam →
 * Canada shipment that is early in its journey and on no master, so a milestone recorded on
 * it does not disturb the shipments the public-tracking fixtures pick (partially delivered,
 * exception, delivered, cancelled). Test data only.
 */

import { execFileSync } from 'node:child_process';
import { expect } from './diagnostics.js';
import { PYTHON, REPO_ROOT } from '../../scripts/pythonInterpreter.mjs';

export async function createMaster(page, tag) {
  await page.goto('/workspace');
  await expect(page.getByRole('heading', { name: 'Workspace', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'New master' }).click();
  await page.getByRole('combobox', { name: /Origin/ }).selectOption('HCM');
  await page.getByRole('textbox', { name: /Master tracking/ }).fill(`AWB-${tag}-${Date.now().toString(36)}`);
  await page.getByRole('textbox', { name: /Gross weight/ }).fill('21');
  await page.getByRole('button', { name: 'Create master' }).click();
  await expect(page).toHaveURL(/\/workspace\/\d+$/);
  const consolidationId = page.url().split('/').pop();
  const heading = page.getByRole('heading', { level: 1 });
  await expect(heading).toContainText('Air Standard');
  const reference = (await heading.textContent()).split('·')[0].trim();
  return { consolidationId, reference };
}

/** Search, then try each offered shipment until the server accepts one. */
export async function addMemberBySearch(page, consolidationId, query) {
  // Two panes (DEC-0277): "+ Add customer" under piece 1 in the tree, then attach a booking.
  await page.getByRole('navigation', { name: 'Master structure' }).getByRole('button', { name: '+ Add customer' }).first().click();
  await page.getByRole('button', { name: 'Attach an existing booking' }).first().click();
  await page.getByRole('searchbox', { name: /Find a confirmed booking/ }).fill(query);
  const results = page.getByRole('list', { name: 'Matching shipments' });
  await expect(results.getByRole('listitem').first()).toBeVisible();
  const offered = await results.getByRole('listitem').count();
  for (let index = 0; index < offered; index += 1) {
    const response = page.waitForResponse(
      (item) =>
        item.url().includes(`/api/v1/consolidations/${consolidationId}/members`) &&
        item.request().method() === 'POST',
    );
    await results.getByRole('listitem').nth(index).getByRole('button', { name: 'Add' }).click();
    if ((await response).ok()) return true;
  }
  return false;
}

export function pickFreeShipment() {
  const script = `
import json, sys
sys.path.insert(0, "backend")
from sqlalchemy import text
from app.core.config import settings
from app.core.db import build_engine

engine = build_engine(settings.database_url)
with engine.connect() as connection:
    row = connection.execute(text("""
        SELECT s.id, s.public_id FROM shipments s
        WHERE s.booking_state = 'confirmed' AND s.route_group = 'VCA'
          AND s.public_id IS NOT NULL
          AND s.operational_state IN ('booked', 'received_at_solaris')
          AND NOT EXISTS (SELECT 1 FROM consolidation_memberships m
                          WHERE m.shipment_id = s.id AND m.removed_at IS NULL)
        ORDER BY s.id DESC LIMIT 1
    """)).fetchone()
print(json.dumps({"id": row[0], "public_id": row[1]} if row else None))
`;
  const stdout = execFileSync(PYTHON, ['-c', script], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  const found = JSON.parse(stdout.trim().split('\n').pop());
  if (!found) throw new Error('The e2e database has no free early-journey VCA shipment.');
  return found;
}
