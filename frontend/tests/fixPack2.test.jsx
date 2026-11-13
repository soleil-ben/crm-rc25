/**
 * Fix pack 2 (UAT round 2): the date conversion (item 2) and the merge confirmation text
 * (item 4). The profile, tags and referral items have their own test files.
 *
 * The date tests use the shape the API actually sends -- a naive UTC timestamp with no zone
 * designator. The account fixtures carry `+00:00`, which parsed correctly before the fix,
 * and that is why the bug reached UAT.
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { parseServerDate } from '../src/shared/serverDate.js';
import { formatDate as accountDate, formatDateTime as accountDateTime } from '../src/account/format.js';
import { formatDateTime as staffDateTime, interpolate } from '../src/utils/format.js';
import { SessionProvider } from '../src/app/SessionContext.jsx';
import { DuplicatesTab } from '../src/features/customers/tabs/DuplicatesTab.jsx';
import {
  detailFixture,
  meFixture,
  renderAccount,
  stubAccountFetch,
} from './accountUtils.jsx';
import { customerFixture, renderWithProviders, stubFetch } from './utils.jsx';

const NAIVE = '2026-10-14T05:19:00';
const TORONTO = 'America/Toronto';

describe('parseServerDate', () => {
  it('reads a naive timestamp as UTC', () => {
    expect(parseServerDate(NAIVE).toISOString()).toBe('2026-10-14T05:19:00.000Z');
    expect(parseServerDate('2026-10-14T05:19:00.123456').toISOString()).toBe(
      '2026-10-14T05:19:00.123Z',
    );
  });

  it('leaves every explicit designator alone', () => {
    expect(parseServerDate('2026-10-14T05:19:00Z').toISOString()).toBe('2026-10-14T05:19:00.000Z');
    expect(parseServerDate('2026-10-14T05:19:00+00:00').toISOString()).toBe(
      '2026-10-14T05:19:00.000Z',
    );
    // The negative offset the staff formatter used to mistake for a naive value.
    expect(parseServerDate('2026-10-14T01:19:00-04:00').toISOString()).toBe(
      '2026-10-14T05:19:00.000Z',
    );
  });

  it('answers null for nothing or garbage', () => {
    expect(parseServerDate(null)).toBeNull();
    expect(parseServerDate('')).toBeNull();
    expect(parseServerDate('not a date')).toBeNull();
  });
});

describe('Customer Account dates (UAT round 2: 05:19 shown where 01:19 was right)', () => {
  // The bug only shows when the browser's own zone is not UTC: `new Date(naive)` reads the
  // value as local time. Pin the zone so these tests mean the same on every machine.
  const previousTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = TORONTO;
  });
  afterAll(() => {
    process.env.TZ = previousTz;
  });

  it('is run where the naive reading would actually be wrong', () => {
    // A guard on the test itself: if this ever passes trivially, the zone pin failed.
    expect(new Date(NAIVE).toISOString()).not.toBe(parseServerDate(NAIVE).toISOString());
  });

  it('formats a naive UTC timestamp in Toronto time', () => {
    const text = accountDateTime(NAIVE, TORONTO);
    expect(text).toMatch(/01:19/);
    expect(text).not.toMatch(/05:19/);
  });

  it('puts a late-evening UTC instant on the right Toronto day', () => {
    // 02:30 UTC on the 15th is 22:30 on the 14th in Toronto.
    expect(accountDate('2026-10-15T02:30:00', TORONTO)).toMatch(/14/);
  });

  it('shows the converted time on the shipment detail itself', async () => {
    stubAccountFetch([
      { path: '/api/v1/account/me', body: meFixture() },
      {
        path: '/api/v1/account/shipments/SX-CAV-7K9D2M4R8T6W',
        body: detailFixture({
          timeline: [
            {
              ...detailFixture().timeline[0],
              occurred_at: NAIVE,
            },
          ],
          last_public_update_at: NAIVE,
        }),
      },
    ]);
    renderAccount('/account/shipments/SX-CAV-7K9D2M4R8T6W');
    await screen.findAllByText(/01:19/);
    expect(document.body.textContent).not.toMatch(/05:19/);
  });

  it('staff and public share the same parser, so staff agrees', () => {
    expect(staffDateTime(NAIVE)).toMatch(/1:19/);
    expect(staffDateTime(NAIVE)).not.toMatch(/5:19/);
  });
});

describe('interpolate (item 4)', () => {
  it('fills every occurrence of every placeholder', () => {
    expect(interpolate('{a} then {b}; {a} again, {b} again', { a: 'X', b: 'Y' })).toBe(
      'X then Y; X again, Y again',
    );
  });

  it('leaves a placeholder with no value visible rather than writing "undefined"', () => {
    expect(interpolate('{a} and {missing}', { a: 1 })).toBe('1 and {missing}');
  });
});

describe('the merge confirmation shows real IDs, never a placeholder (item 4)', () => {
  it('names both customers everywhere the sentence mentions them', async () => {
    const user = userEvent.setup();
    const candidate = { ...customerFixture, id: 4, public_id: 'STCA-000004', full_name: 'Nguyen Thi Bich Hanh' };
    stubFetch([
      {
        path: '/auth/me',
        body: {
          user: { id: 1, full_name: 'Admin', email: 'admin@demo.example.com', role: 'admin' },
          permissions: ['customer:read', 'duplicate:review', 'customer:merge'],
          environment: 'test',
          is_demo_environment: false,
        },
      },
      {
        path: '/customers/1/duplicate-candidates',
        body: {
          candidates: [{ customer: candidate, matched_on: ['phone'], confidence: 55, requires_review: true }],
          guidance: 'Review each candidate before deciding.',
        },
      },
    ]);
    renderWithProviders(
      <SessionProvider>
        <Routes>
          <Route path="/customers/:id" element={<DuplicatesTab customer={customerFixture} />} />
        </Routes>
      </SessionProvider>,
      { route: '/customers/1' },
    );
    await screen.findByRole('table', { name: /Compare with/ });
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    const dialog = await screen.findByRole('dialog', { name: 'Merge these two customers' });

    const text = dialog.textContent;
    expect(text).not.toMatch(/\{source\}|\{target\}/);
    expect(text).toMatch(/move to STCA-000001; STCA-000004 is retired/);
    expect(within(dialog).getByLabelText(/Type STCA-000004 to confirm/)).toBeInTheDocument();
  });
});
