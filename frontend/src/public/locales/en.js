/**
 * English copy for the public tracking page.
 *
 * Kept separate from the staff catalogue (`src/i18n/en.js`) on purpose: the two are
 * written for different readers. The staff catalogue can say "operational state" and
 * "leg"; this one is read by somebody standing in a post office wondering where their
 * parcel is.
 *
 * `vi.js` must define exactly the same keys. `tests/publicI18n.test.js` fails if the two
 * catalogues drift apart, which is the failure mode a bilingual page actually has --
 * not a missing translation file, but one key quietly added to only one of them.
 */

export const en = {
  meta: {
    // Deliberately generic and constant. A tracking reference must never reach the
    // document title (CRM.md section 10).
    documentTitle: 'Track your shipment — Solaris Express',
    languageName: 'English',
    languageCode: 'en',
    locale: 'en-CA',
  },
  brand: {
    nameFirst: 'Solaris',
    nameSecond: 'Express',
    tagline: 'Parcel tracking',
  },
  a11y: {
    skipToContent: 'Skip to main content',
    languageSwitcher: 'Language',
    mainContent: 'Main content',
    loading: 'Loading tracking information',
    resultRegion: 'Tracking result',
    timelineRegion: 'Shipment updates',
    packagesRegion: 'Packages in this shipment',
  },
  landing: {
    title: 'Track your shipment',
    instruction:
      'Enter the Solaris Shipment ID or package reference from your label or receipt.',
    fieldLabel: 'Solaris Shipment ID or package reference',
    placeholder: 'SX-CAV-7K9D2M4R8T6W',
    exampleLabel: 'Example',
    exampleHint:
      'A shipment ID looks like SX-CAV-7K9D2M4R8T6W. A package reference adds a number, like SX-CAV-7K9D2M4R8T6W-01. Capitals and spaces do not matter.',
    submit: 'Track',
    submitting: 'Checking…',
    emptyError: 'Enter a Solaris Shipment ID or package reference.',
    helpLink: 'Contact Solaris Express',
    privacyNote:
      'We show only the status of the shipment you asked about. Nothing you type here is stored in your browser.',
  },
  result: {
    summaryTitle: 'Shipment summary',
    shipmentId: 'Solaris Shipment ID',
    copyId: 'Copy shipment ID',
    copied: 'Copied',
    route: 'Route',
    status: 'Status',
    from: 'From',
    to: 'To',
    packages: 'Packages',
    scannedPackage: 'You scanned',
    estimatedDelivery: 'Estimated delivery',
    estimatedBadge: 'Estimated',
    estimatedNote: 'An estimate provided when the shipment was booked. It is not a guarantee.',
    deliveredOn: 'Delivered',
    cancelledOn: 'Cancelled',
    packagesTitle: 'Packages',
    packageSelected: 'The package you scanned',
    packageCancelled: 'Cancelled',
    packageDelivered: 'Delivered',
    timelineTitle: 'Updates',
    timelineEmpty: 'No updates have been published for this shipment yet.',
    timelineEmptyBody:
      'Solaris publishes an update when the shipment reaches a milestone we can confirm. Check back later.',
    appliesTo: 'Applies to',
    trackAnother: 'Track another shipment',
    unknownCity: 'Not specified',
  },
  freshness: {
    label: 'How this shipment is tracked',
    manual_updates: 'Updates entered by Solaris staff',
    manual_updates_detail:
      'Each update below was recorded by a member of our team when it was confirmed. This page does not refresh by itself.',
    external_link_only: 'Carrier link only',
    external_link_only_detail:
      'Solaris has not published its own updates for this shipment. The carrier’s own tracking page is linked below. We do not read that page for you.',
    no_public_milestones: 'No updates published yet',
    no_public_milestones_detail:
      'The booking is confirmed. Solaris has not published a milestone for it yet. This page does not refresh by itself.',
    tracking_unavailable: 'Tracking unavailable',
    tracking_unavailable_detail:
      'We do not have tracking information for this shipment at the moment. Please contact Solaris Express.',
    demo: 'Demo data',
    demo_detail:
      'This is a synthetic development record. It is not a real shipment and the information below is invented.',
    cancelled: 'Booking cancelled',
    cancelled_detail:
      'This booking was cancelled. Please contact Solaris Express if you were expecting it to ship.',
    lastUpdate: 'Latest update',
    sourceManual: 'Manual update',
  },
  callout: {
    exceptionTitle: 'This shipment needs attention',
    exceptionBody:
      'Something has interrupted this shipment. Please contact Solaris Express with your Solaris Shipment ID and we will look into it.',
    unavailableTitle: 'We cannot show tracking for this shipment',
    unavailableBody:
      'Please contact Solaris Express with your Solaris Shipment ID and we will help.',
    contact: 'Contact Solaris Express',
    carrierLink: '{{name}}: open the tracking page',
    carrierLinkNote:
      'This opens the carrier’s own website in a new tab. Solaris does not read that page, so the two may disagree.',
    // Generic leg names (owner, 2026-10-22): never a vendor or carrier name.
    trackingNames: {
      master_tracking: 'Master Tracking',
      last_mile_tracking: 'Last Mile Tracking',
    },
  },
  errors: {
    notFoundTitle: 'We could not find that shipment',
    notFoundBody:
      'Check the Solaris Shipment ID or package reference on your label or receipt and try again. It looks like SX-CAV-7K9D2M4R8T6W.',
    rateLimitedTitle: 'Too many lookups',
    rateLimitedBody:
      'You have made a lot of tracking requests from this connection. Please wait about {{seconds}} seconds and try again.',
    rateLimitedBodyGeneric:
      'You have made a lot of tracking requests from this connection. Please wait a moment and try again.',
    networkTitle: 'We could not reach Solaris Express',
    networkBody: 'Check your connection and try again.',
    tryAgain: 'Try again',
  },
  routes: {
    VCA: 'Vietnam to Canada',
    CAV: 'Canada to Vietnam',
    CAD: 'Within Canada',
    XUS: 'Canada and the United States',
  },
  countries: {
    CA: 'Canada',
    VN: 'Vietnam',
    US: 'United States',
  },
  status: {
    booked: 'Booked',
    awaiting_parcel: 'Waiting for your parcel',
    received_at_solaris: 'Received at warehouse',
    processing: 'Being processed',
    departed_origin: 'Left the origin country',
    in_transit: 'In transit',
    customs_processing: 'With customs',
    arrived_destination: 'Arrived in the destination country',
    out_for_delivery: 'Out for delivery',
    partially_delivered: 'Partly delivered',
    delivered: 'Delivered',
    delivery_attempted: 'Delivery attempted',
    exception: 'Delayed',
    return_in_progress: 'Being returned',
    returned: 'Returned',
    cancelled: 'Cancelled',
    tracking_unavailable: 'Tracking unavailable',
  },
  progress: {
    // {{delivered}} of {{active}} — the "1 of 3 packages delivered" line.
    summaryOne: '{{delivered}} of {{active}} package delivered',
    summaryMany: '{{delivered}} of {{active}} packages delivered',
    cancelledCountOne: '{{count}} package was cancelled',
    cancelledCountMany: '{{count}} packages were cancelled',
  },
};

export default en;
