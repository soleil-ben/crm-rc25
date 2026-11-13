/**
 * Phase 15: the Customer Account timeline shows the standard wording for each published
 * event type in the customer's language, with the staff's published text beneath it.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import {
  clearBrowserStorage,
  detailFixture,
  meFixture,
  renderAccount,
  stubAccountFetch,
} from './accountUtils.jsx';

const ME = '/api/v1/account/me';
const DETAIL = '/api/v1/account/shipments/SX-CAV-7K9D2M4R8T6W';
const URL = '/account/shipments/SX-CAV-7K9D2M4R8T6W';

function entry(overrides) {
  return { ...detailFixture().timeline[0], ...overrides };
}

async function show(timeline, locale = 'en') {
  stubAccountFetch([
    { path: ME, body: meFixture({ preferred_language: locale }) },
    { path: DETAIL, body: detailFixture({ timeline }) },
  ]);
  renderAccount(URL, { locale });
  await screen.findByRole('heading', { name: 'SX-CAV-7K9D2M4R8T6W', level: 1 });
}

beforeEach(clearBrowserStorage);

describe('the customer timeline wording', () => {
  it('shows the standard sentence with the typed text beneath it, in English', async () => {
    await show([
      entry({
        event_type: 'delivered_to_collection_point',
        status: 'out_for_delivery',
        message: 'Pick up at the Quận 1 office before 5 pm.',
        message_template_key: null,
      }),
    ]);
    const standard = screen.getByText('Your shipment is ready to collect at the pickup point.');
    expect(standard).toHaveClass('ca-timeline__message');
    const note = screen.getByText('Pick up at the Quận 1 office before 5 pm.');
    expect(note.closest('p')).toHaveClass('ca-timeline__note');
    expect(note.closest('p')).toHaveTextContent('Note from Solaris Express');
  });

  it('shows the standard sentence and a standard update in Vietnamese', async () => {
    await show(
      [
        entry({
          event_type: 'customs_processing',
          status: 'customs_processing',
          message: 'Your shipment is being held at customs. We will update you when it is released.',
          message_template_key: 'customs_processing.held.v1',
        }),
      ],
      'vi',
    );
    expect(screen.getByText('Lô hàng của bạn đang làm thủ tục hải quan.')).toBeInTheDocument();
    expect(
      screen.getByText(/Lô hàng của bạn đang bị giữ tại hải quan/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/being held at customs/)).toBeNull();
  });

  it('does not repeat a published text that says what the standard sentence says', async () => {
    await show([
      entry({
        event_type: 'out_for_delivery',
        status: 'out_for_delivery',
        message: 'Your shipment is out for delivery.',
        message_template_key: 'out_for_delivery.v1',
      }),
    ]);
    expect(screen.getAllByText('Your shipment is out for delivery.')).toHaveLength(1);
    expect(document.querySelector('.ca-timeline__note')).toBeNull();
  });

  it('falls back to a neutral sentence for an event type it does not know', async () => {
    await show([entry({ event_type: 'something_new', message: 'Typed by staff.' })]);
    expect(screen.getByText('Your shipment has a new update.')).toBeInTheDocument();
    expect(screen.getByText('Typed by staff.')).toBeInTheDocument();
  });

  it('words a step on one parcel of several as that parcel, not the shipment', async () => {
    await show([
      entry({
        event_type: 'delivered_to_recipient',
        status: 'delivered',
        scope: 'package',
        message: 'Left with the neighbour.',
        message_template_key: null,
        package_references: ['SX-CAV-7K9D2M4R8T6W-01'],
      }),
      entry({ event_type: 'in_transit', status: 'in_transit', scope: 'shipment', message: '' }),
    ]);
    expect(screen.getByText('One of your parcels has been delivered.')).toBeInTheDocument();
    expect(screen.queryByText('Your shipment has been delivered.')).toBeNull();
    expect(screen.getByText('Your shipment is on its way.')).toBeInTheDocument();
  });

  it('words a parcel step in Vietnamese too', async () => {
    await show(
      [entry({ event_type: 'returned', status: 'returned', scope: 'package', message: '' })],
      'vi',
    );
    expect(screen.getByText('Một kiện hàng của bạn đã được trả về người gửi.')).toBeInTheDocument();
  });

  it('never renders an internal note, even when a response carries one', async () => {
    await show([
      entry({
        event_type: 'in_transit',
        internal_detail: 'SENTINEL-INTERNAL-NOTE',
        internal_notes: 'SENTINEL-STAFF-NOTE',
      }),
    ]);
    expect(document.body.textContent).not.toContain('SENTINEL');
    expect(screen.getByText('Your shipment is on its way.')).toBeInTheDocument();
  });
});
