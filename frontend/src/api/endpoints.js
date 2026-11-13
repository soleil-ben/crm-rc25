/** Named endpoint wrappers, mirroring the FastAPI OpenAPI contract. */

import { api, downloadBlob, upload } from './client.js';

export const authApi = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
  // RC-UAT-21 Phase B (DEC-0231): the signed-in staff member's own password.
  changePassword: (payload) => api.post('/auth/password/change', payload),
};

export const customersApi = {
  list: (params) => api.get('/customers', params),
  create: (payload) => api.post('/customers', payload),
  get: (id) => api.get(`/customers/${id}`),
  update: (id, payload) => api.patch(`/customers/${id}`, payload),
  archive: (id, reason) => api.post(`/customers/${id}/archive`, { reason }),
  restore: (id) => api.post(`/customers/${id}/restore`),
  duplicateCheck: (payload) => api.post('/customers/duplicate-check', payload),
  duplicateCandidates: (id) => api.get(`/customers/${id}/duplicate-candidates`),
  merge: (payload) => api.post('/customers/merge', payload),
  financials: (id) => api.get(`/customers/${id}/financials`),
  addresses: (id, params) => api.get(`/customers/${id}/addresses`, params),
  createAddress: (id, payload) => api.post(`/customers/${id}/addresses`, payload),
  updateAddress: (addressId, payload) => api.patch(`/addresses/${addressId}`, payload),
  archiveAddress: (addressId) => api.delete(`/addresses/${addressId}`),
  interactions: (id, params) => api.get(`/customers/${id}/interactions`, params),
  createInteraction: (id, payload) => api.post(`/customers/${id}/interactions`, payload),
  consent: (id) => api.get(`/customers/${id}/consent`),
  recordConsent: (id, payload) => api.post(`/customers/${id}/consent`, payload),
  // UAT round 4: `suppression:add` (Marketing and Admin). Evidence and reason required.
  suppressAddress: (id, payload) => api.post(`/customers/${id}/consent/suppressions`, payload),
  referrals: (id) => api.get(`/customers/${id}/referrals`),
  createReferral: (id, payload) => api.post(`/customers/${id}/referrals`, payload),
  serviceIssues: (id) => api.get(`/customers/${id}/service-issues`),
  createServiceIssue: (id, payload) => api.post(`/customers/${id}/service-issues`, payload),
};

export const tasksApi = {
  list: (params) => api.get('/tasks', params),
  mine: (params) => api.get('/tasks/mine', params),
  create: (payload) => api.post('/tasks', payload),
  update: (id, payload) => api.patch(`/tasks/${id}`, payload),
  complete: (id, payload) => api.post(`/tasks/${id}/complete`, payload),
};

export const segmentsApi = {
  list: () => api.get('/segments'),
  fields: () => api.get('/segments/fields'),
  get: (id) => api.get(`/segments/${id}`),
  create: (payload) => api.post('/segments', payload),
  update: (id, payload) => api.patch(`/segments/${id}`, payload),
  remove: (id) => api.delete(`/segments/${id}`),
  members: (id, params) => api.get(`/segments/${id}/members`, params),
  preview: (definition, limit = 10) => api.post('/segments/preview', { definition, limit }),
};

export const shipmentsApi = {
  list: (params) => api.get('/shipments', params),
  get: (id) => api.get(`/shipments/${id}`),
  meta: () => api.get('/shipments/meta'),
  createDraft: (payload) => api.post('/shipments', payload),
  update: (id, payload) => api.patch(`/shipments/${id}`, payload),
  confirm: (id, idempotencyKey) =>
    api.post(`/shipments/${id}/confirm`, { idempotency_key: idempotencyKey }),
  cancel: (id, reason) => api.post(`/shipments/${id}/cancel`, { reason }),
  rebook: (id, payload) => api.post(`/shipments/${id}/rebook`, payload),
  updateFinancials: (id, payload) => api.patch(`/shipments/${id}/financials`, payload),

  packages: (id) => api.get(`/shipments/${id}/packages`),
  addPackage: (id, payload) => api.post(`/shipments/${id}/packages`, payload),
  updatePackage: (packageId, payload) => api.patch(`/packages/${packageId}`, payload),
  duplicatePackage: (packageId) => api.post(`/packages/${packageId}/duplicate`),
  cancelPackage: (packageId, reason) => api.post(`/packages/${packageId}/cancel`, { reason }),
  removeDraftPackage: (packageId) => api.delete(`/packages/${packageId}`),

  legs: (id) => api.get(`/shipments/${id}/legs`),
  createLeg: (id, payload) => api.post(`/shipments/${id}/legs`, payload),
  updateLeg: (legId, payload) => api.patch(`/legs/${legId}`, payload),
  deleteLeg: (legId) => api.delete(`/legs/${legId}`),
  addTrackingReference: (legId, payload) =>
    api.post(`/legs/${legId}/tracking-references`, payload),
  retireTrackingReference: (referenceId, reason) =>
    api.post(`/tracking-references/${referenceId}/retire`, { reason }),

  events: (id, params) => api.get(`/shipments/${id}/events`, params),
  recordEvent: (id, payload) => api.post(`/shipments/${id}/events`, payload),
  voidEvent: (eventId, reason) => api.post(`/events/${eventId}/void`, { reason }),
  // RC-UAT-25 item 6: correct a recorded event; its edit history.
  editEvent: (id, payload) => api.post(`/shipments/${id}/events/edit`, payload),
  eventRevisions: (id) => api.get(`/shipments/${id}/event-revisions`),

  labelPreview: (id) => api.get(`/shipments/${id}/label-preview`),
  labelJobs: (id) => api.get(`/shipments/${id}/label-jobs`),
  lookup: (reference) => api.get('/shipments/lookup', { reference }),
  search: (q, limit) => api.get('/search/shipments', { q, limit }),
};

/**
 * Reports (Phase 5A).
 *
 * The definitions call is separate from the data call so a definition tooltip does not
 * cost eight aggregate queries, and so a role learns which reports exist for it rather
 * than inferring that from an empty payload.
 */
export const reportsApi = {
  definitions: () => api.get('/reports/definitions'),
  read: (params) => api.get('/reports', params),
};

/**
 * CSV customer import.
 *
 * Preview and commit are multipart, so they bypass the JSON client. The commit sends the
 * same file again with the digest the preview returned: the server re-validates from
 * scratch and refuses a file that changed since it was reviewed.
 */
export const importsApi = {
  fields: () => api.get('/imports/customers/fields'),
  batches: (params) => api.get('/imports/batches', params),
  batch: (publicId) => api.get(`/imports/batches/${publicId}`),
  preview: (file) => {
    const body = new FormData();
    body.append('file', file);
    return upload('/imports/customers/preview', body);
  },
  commit: (file, { contentSha256, conflictPolicy, decisions }) => {
    const body = new FormData();
    body.append('file', file);
    body.append('content_sha256', contentSha256);
    body.append('confirm', 'true');
    body.append('conflict_policy', conflictPolicy);
    body.append('decisions_json', JSON.stringify(decisions || {}));
    return upload('/imports/customers/commit', body);
  },
};

/**
 * RC-UAT-21 Phase A: shipment import and legacy history baseline (DEC-0230).
 *
 * `kind` is `shipments` or `legacy-history` (the URL segment). Dry run first; the commit
 * re-sends the same file with the digest the dry run returned, and the server refuses it
 * unless the same staff member dry-ran the same bytes and options.
 */
export const bulkImportsApi = {
  fields: (kind) => api.get(`/imports/${kind}/fields`),
  dryRun: (kind, file, { cutoffDate } = {}) => {
    const body = new FormData();
    body.append('file', file);
    if (cutoffDate) body.append('cutoff_date', cutoffDate);
    return upload(`/imports/${kind}/dry-run`, body);
  },
  commit: (kind, file, { contentSha256, cutoffDate } = {}) => {
    const body = new FormData();
    body.append('file', file);
    body.append('content_sha256', contentSha256);
    body.append('confirm', 'true');
    if (cutoffDate) body.append('cutoff_date', cutoffDate);
    return upload(`/imports/${kind}/commit`, body);
  },
  baselines: () => api.get('/imports/legacy-history/baselines'),
  voidBaseline: (batchPublicId, reason) =>
    api.post(`/imports/legacy-history/baselines/${batchPublicId}/void`, {
      reason,
      confirm: true,
    }),
  legacyShipments: (params) => api.get('/legacy-shipments', params),
  legacyShipment: (id) => api.get(`/legacy-shipments/${id}`),
};

/**
 * Customer Account review (Phase 10 API, Phase 12 screens).
 *
 * Staff endpoints, under `/api/v1`, guarded by `customer_account:review` and — for the
 * four decisions — `customer_account:approve` as well. They are **not** Customer Account
 * endpoints and must never be called from `src/account`, which has its own client and no
 * import path to this file.
 */
export const customerAccountReviewApi = {
  registrations: (params) => api.get('/customer-account/registrations', params),
  registration: (reference) => api.get(`/customer-account/registrations/${reference}`),
  duplicateCandidates: (reference) =>
    api.get(`/customer-account/registrations/${reference}/duplicate-candidates`),
  preview: (reference, params) =>
    api.get(`/customer-account/registrations/${reference}/preview`, params),
  acknowledgeDisclosure: (reference, payload) =>
    api.post(`/customer-account/registrations/${reference}/disclosure-acknowledgement`, payload),
  approveCreateNew: (reference, payload) =>
    api.post(`/customer-account/registrations/${reference}/approve/create-new`, payload),
  approveLinkExisting: (reference, payload) =>
    api.post(`/customer-account/registrations/${reference}/approve/link-existing`, payload),
  reject: (reference, payload) =>
    api.post(`/customer-account/registrations/${reference}/reject`, payload),
  // Sprint 13 Lane A, A-1: the account lifecycle, addressed by identity rather than by
  // registration because a suspension acts on an account approved long ago.
  identity: (reference) => api.get(`/customer-account/identities/${reference}`),
  suspend: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/suspend`, payload),
  reinstate: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/reinstate`, payload),
  // Admin only (DEC-0126); the server checks `customer_account:deactivate`.
  deactivate: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/deactivate`, payload),
  // RC-UAT-21 Phase B (DEC-0231): Admin only, the same permission as deactivation.
  reactivate: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/reactivate`, payload),
  // RC-UAT-25 item 2: Admin only, the same permission as deactivation.
  changeSignInEmail: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/sign-in-email`, payload),
  deactivatedIdentities: () => api.get('/customer-account/identities-deactivated'),
  // RC-UAT-22 (B-13): approved accounts that lost their customer. Admin only, the same
  // permission as reinstatement.
  orphanedIdentities: () => api.get('/customer-account/identities-orphaned'),
  relinkPreview: (reference, customerPublicId) =>
    api.get(`/customer-account/identities/${reference}/relink-preview`, {
      customer_public_id: customerPublicId,
    }),
  relink: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/relink`, payload),
  closeOrphan: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/close-orphan`, payload),
  // Fix pack 2: post-approval profile changes (FIELD_MATRIX §5).
  profileProposals: () => api.get('/customer-account/profile-proposals'),
  profileProposal: (reference) =>
    api.get(`/customer-account/identities/${reference}/profile-proposal`),
  decideProfileProposal: (reference, payload) =>
    api.post(`/customer-account/identities/${reference}/profile-proposal/decide`, payload),
};

export const opsApi = {
  dashboard: (days) => api.get('/dashboard/summary', { days }),
  search: (q, limit) => api.get('/search', { q, limit }),
  tags: () => api.get('/tags'),
  createTag: (payload) => api.post('/tags', payload),
  assignableStaff: () => api.get('/staff/assignable'),
  staff: () => api.get('/staff'),
  createStaff: (payload) => api.post('/staff', payload),
  updateStaff: (id, payload) => api.patch(`/staff/${id}`, payload),
  settings: () => api.get('/settings'),
  updateSettings: (payload) => api.patch('/settings', payload),
  runRetentionRules: () => api.post('/settings/run-retention-rules'),
  audit: (params) => api.get('/audit', params),
  enums: () => api.get('/meta/enums'),
};

/**
 * Integration infrastructure (Phase 4A).
 *
 * Read-only health plus two actions. There is deliberately no `connect` and no
 * `verify` call, because neither could perform a real operation: no provider account
 * is configured and the adapter registry is empty.
 */
export const integrationsApi = {
  health: () => api.get('/integrations/health'),
  jobs: (params) => api.get('/integrations/jobs', params),
  retryJob: (id) => api.post(`/integrations/jobs/${id}/retry`),
  disableConnection: (id, reason) =>
    api.post(`/integrations/connections/${id}/disable`, { reason }),
};

/**
 * Consolidations, pricing and quotes (Phases 13B-13D): the unified workspace.
 *
 * Staff only. Every call here carries vendor cost or the vendor's reference, so the server
 * requires `tariff:read` (Operations and Admin) on top of the shipment and financial
 * permissions; the navigation entry is hidden for the other roles, and the routes refuse on
 * their own. Origin + service pick the base rate (Air Standard, Air Express, UPS, Sea).
 */
export const consolidationsApi = {
  list: (params) => api.get('/consolidations', params),
  get: (id) => api.get(`/consolidations/${id}`),
  create: (payload) => api.post('/consolidations', payload),
  update: (id, payload) => api.patch(`/consolidations/${id}`, payload),
  addMember: (id, shipmentId) => api.post(`/consolidations/${id}/members`, { shipment_id: shipmentId }),
  removeMember: (id, shipmentId, reason) =>
    api.post(`/consolidations/${id}/members/${shipmentId}/remove`, { reason }),
  book: (id) => api.post(`/consolidations/${id}/book`),
  // Phase 14: master milestones that fan out to every member; close or cancel a master.
  recordEvent: (id, payload) => api.post(`/consolidations/${id}/events`, payload),
  complete: (id) => api.post(`/consolidations/${id}/complete`),
  cancel: (id, reason) => api.post(`/consolidations/${id}/cancel`, { reason }),
  cartons: (id) => api.get(`/consolidations/${id}/cartons`),
  replaceCartons: (id, cartons) => api.patch(`/consolidations/${id}/cartons`, { cartons }),
  pricing: (id) => api.get(`/consolidations/${id}/pricing`),
  // Owner decision 8: a booked master locks its items and fees; Admin unlocks with a reason.
  unlock: (id, reason) => api.post(`/consolidations/${id}/unlock`, { reason }),
  relock: (id, reason) => api.post(`/consolidations/${id}/relock`, reason ? { reason } : {}),
  // Cost and quote method (DEC-0258 / DEC-0262 / DEC-0266): packages, manual pricing.
  packages: (id) => api.get(`/consolidations/${id}/packages`),
  setPackageNote: (id, sequence, note) =>
    api.patch(`/consolidations/${id}/packages/${sequence}/note`, { customer_note: note || null }),
  setPackageMember: (id, shipmentId, sequence) =>
    api.patch(`/consolidations/${id}/members/${shipmentId}/package`, {
      carton_sequence: sequence === '' || sequence === null ? null : Number(sequence),
    }),
  setPacked: (id, sequence, packed) =>
    api.patch(`/consolidations/${id}/packages/${sequence}/packed`, { packed_as_one_box: packed }),
  // Workspace redesign (DEC-0272): last-mile tracking per piece; add a customer to a piece.
  setPieceTracking: (id, sequence, value) =>
    api.patch(`/consolidations/${id}/packages/${sequence}/tracking`, {
      last_mile_tracking: value || null,
    }),
  addCustomer: (id, payload) => api.post(`/consolidations/${id}/customers`, payload),
  updateCustomer: (id, shipmentId, payload) =>
    api.patch(`/consolidations/${id}/customers/${shipmentId}`, payload),
  manualPricing: (id) => api.get(`/consolidations/${id}/manual-pricing`),
  setManualPricing: (id, payload) => api.patch(`/consolidations/${id}/manual-pricing`, payload),
};

/** The confirmed cost and quote method's settings (DEC-0266 / DEC-0267). */
export const methodApi = {
  settings: () => api.get('/pricing/method-settings'),
  update: (payload) => api.patch('/pricing/method-settings', payload),
  setSeaCost: (payload) => api.post('/pricing/sea-cost', payload),
};

/** Admin "Import Kango rate sheet" (DEC-0264) and the approver permission (DEC-0268). */
export const rateSheetApi = {
  importSheet: (file, { effectiveFrom, label }) => {
    const body = new FormData();
    body.append('file', file);
    body.append('effective_from', effectiveFrom);
    if (label) body.append('label', label);
    return upload('/tariffs/rate-sheet/import', body);
  },
  diff: (versionId) => api.get(`/tariffs/versions/${versionId}/rate-sheet-diff`),
  history: () => api.get('/tariffs/rate-sheet/history'),
  confirm: (versionId) => api.post(`/tariffs/versions/${versionId}/approve`),
  discard: (versionId, reason) => api.post(`/tariffs/versions/${versionId}/reject`, { reason }),
  rollback: (versionId) => api.post(`/tariffs/versions/${versionId}/rollback`),
  pendingCount: () => api.get('/tariffs/intake/pending-count'),
  grants: () => api.get('/staff/permission-grants'),
  grant: (userId, permission = 'tariff:approve') =>
    api.post(`/staff/${userId}/grants/${permission}`),
  revoke: (userId, permission = 'tariff:approve') =>
    api.delete(`/staff/${userId}/grants/${permission}`),
};

export const itemsApi = {
  list: (shipmentId) => api.get(`/shipments/${shipmentId}/items`),
  add: (shipmentId, payload) => api.post(`/shipments/${shipmentId}/items`, payload),
  update: (shipmentId, itemId, payload) =>
    api.patch(`/shipments/${shipmentId}/items/${itemId}`, payload),
  remove: (shipmentId, itemId) => api.post(`/shipments/${shipmentId}/items/${itemId}/remove`),
};

export const pricingApi = {
  settings: () => api.get('/pricing/settings'),
  // Phase 14: Settings -> Pricing (Admin, `settings:manage`); the server validates and audits.
  updateSettings: (payload) => api.patch('/pricing/settings', payload),
  policies: () => api.get('/pricing/surcharge-policies'),
  setPolicy: (section, stt, payload) =>
    api.patch(`/pricing/surcharge-policies/${section}/${stt}`, payload),
  // Phase 14: the printable customer quote of a finalised version (revenue only).
  quoteDocument: (shipmentId, version) =>
    api.get(`/shipments/${shipmentId}/quotes/${version}/document`),
  feeLines: (shipmentId) => api.get(`/shipments/${shipmentId}/fee-lines`),
  addFeeLine: (shipmentId, payload) => api.post(`/shipments/${shipmentId}/fee-lines`, payload),
  removeFeeLine: (shipmentId, lineId) =>
    api.post(`/shipments/${shipmentId}/fee-lines/${lineId}/remove`),
  // Owner, 2026-10-22: the vendor's quoted amount on a line quoted case by case (HCM row 27).
  setFeeLineAmount: (shipmentId, lineId, amountVnd) =>
    api.patch(`/shipments/${shipmentId}/fee-lines/${lineId}`, {
      manual_unit_price_vnd: amountVnd,
    }),
  // Owner, 2026-10-23 (DEC-0228): the vendor's cost (VND) and/or the customer price (CAD).
  setFeeLinePrices: (shipmentId, lineId, payload) =>
    api.patch(`/shipments/${shipmentId}/fee-lines/${lineId}`, payload),
  quotes: (shipmentId) => api.get(`/shipments/${shipmentId}/quotes`),
  reprice: (shipmentId) => api.post(`/shipments/${shipmentId}/quotes`),
  confirmRate: (shipmentId, payload) =>
    api.post(`/shipments/${shipmentId}/quotes/confirm-rate`, payload),
  finalize: (shipmentId, payload) => api.post(`/shipments/${shipmentId}/quotes/finalize`, payload),
  // Phase 13G (OD-77): send the finalised quote to the customer; read and withdraw offers.
  offers: (shipmentId) => api.get(`/shipments/${shipmentId}/quote-offers`),
  sendQuote: (shipmentId) => api.post(`/shipments/${shipmentId}/quotes/send`),
  withdrawOffer: (offerId, reason) => api.post(`/quote-offers/${offerId}/withdraw`, { reason }),
  // Phase 15: send the quote email again (failed, or no address and one was added).
  resendOfferEmail: (offerId) => api.post(`/quote-offers/${offerId}/resend-email`),
};

export const tariffsApi = {
  versions: () => api.get('/tariffs/versions'),
  // Phase 14: the read-only tariff browser and the manual workbook import (a draft).
  version: (versionId) => api.get(`/tariffs/versions/${versionId}`),
  products: (versionId) => api.get(`/tariffs/versions/${versionId}/products`),
  product: (versionId, productId) =>
    api.get(`/tariffs/versions/${versionId}/products/${productId}`),
  accessorials: (versionId) => api.get(`/tariffs/versions/${versionId}/accessorials`),
  beyondRates: (versionId) => api.get(`/tariffs/versions/${versionId}/beyond-rates`),
  // RC-20: a version's import warnings, a page at a time, and the owner-confirmed steps.
  warnings: (versionId, { limit = 25, offset = 0 } = {}) =>
    api.get(`/tariffs/versions/${versionId}/warnings`, { limit, offset }),
  fxHistory: (limit = 30) => api.get('/fx/history', { limit }),
  importWorkbook: (file, { effectiveFrom, label }) => {
    const body = new FormData();
    body.append('file', file);
    body.append('effective_from', effectiveFrom);
    if (label) body.append('label', label);
    return upload('/tariffs/versions/import', body);
  },
  surcharges: (versionId, params) => api.get(`/tariffs/versions/${versionId}/surcharges`, params),
  fxLatest: () => api.get('/fx/latest'),
  // Phase 13H (OD-76): vendor rate emails become draft versions; the approver decides.
  intake: (params) => api.get('/tariffs/intake', params),
  uploadIntake: (file) => {
    const body = new FormData();
    body.append('file', file);
    return upload('/tariffs/intake/upload', body);
  },
  release: (intakeId) => api.post(`/tariffs/intake/${intakeId}/release`),
  reprocess: (intakeId) => api.post(`/tariffs/intake/${intakeId}/reprocess`),
  // Phase 15: drafts awaiting approval and held senders, for the approver badge.
  pendingCount: () => api.get('/tariffs/intake/pending-count'),
  intakeSettings: () => api.get('/tariffs/intake/settings'),
  updateIntakeSettings: (payload) => api.patch('/tariffs/intake/settings', payload),
  diff: (versionId) => api.get(`/tariffs/versions/${versionId}/diff`),
  approve: (versionId) => api.post(`/tariffs/versions/${versionId}/approve`),
  reject: (versionId, reason) => api.post(`/tariffs/versions/${versionId}/reject`, { reason }),
};

/**
 * Finance (Phase 13E). Invoices, payments, receipts and receivables need `financial:read`;
 * vendor bills, payables and profitability also `tariff:read` (vendor cost). Refunds, voids
 * and reopening a closed month are Admin's (`financial:adjust`). The server enforces all of
 * it; the screens only hide what a role cannot use.
 */
export const financeApi = {
  // Phase 15: accepted quotes whose shipment has no live invoice (read-only).
  acceptedNotInvoiced: () => api.get('/finance/accepted-not-invoiced'),
  settings: () => api.get('/finance/settings'),
  // Phase 14: invoice due days (Admin, `settings:manage`).
  updateSettings: (payload) => api.patch('/finance/settings', payload),
  // RC-UAT-20 (DEC-0227): the GST/HST rate per province; Admin edits (`settings:manage`).
  taxRates: () => api.get('/finance/tax-rates'),
  updateTaxRate: (provinceCode, payload) =>
    api.patch(`/finance/tax-rates/${provinceCode}`, payload),
  invoices: (params) => api.get('/invoices', params),
  invoice: (id) => api.get(`/invoices/${id}`),
  invoiceDocument: (id) => api.get(`/invoices/${id}/document`),
  shipmentInvoice: (shipmentId) => api.get(`/shipments/${shipmentId}/invoice`),
  // RC-UAT-25 item 8 (Ben 2026-10-25): the shipment page's quote / cost summary and next step.
  shipmentFinancialSummary: (shipmentId) =>
    api.get(`/shipments/${shipmentId}/financial-summary`),
  issueInvoice: (shipmentId, taxRatePercent = 0) =>
    api.post(`/shipments/${shipmentId}/invoice`, { tax_rate_percent: taxRatePercent }),
  recordPayment: (id, payload) => api.post(`/invoices/${id}/payments`, payload),
  voidInvoice: (id, reason) => api.post(`/invoices/${id}/void`, { reason }),
  refund: (paymentId, payload) => api.post(`/payments/${paymentId}/refund`, payload),
  receipt: (paymentId) => api.get(`/payments/${paymentId}/receipt`),
  vendorInvoices: (consolidationId) => api.get(`/consolidations/${consolidationId}/vendor-invoices`),
  enterVendorInvoice: (consolidationId, payload) =>
    api.post(`/consolidations/${consolidationId}/vendor-invoices`, payload),
  approveVendorInvoice: (id, payload) => api.post(`/vendor-invoices/${id}/approve`, payload),
  vendorInvoicePaid: (id, payload) => api.post(`/vendor-invoices/${id}/paid`, payload),
  voidVendorInvoice: (id, reason) => api.post(`/vendor-invoices/${id}/void`, { reason }),
  arAging: () => api.get('/finance/ar-aging'),
  ap: () => api.get('/finance/ap'),
  profitability: (month) => api.get('/finance/profitability', { month }),
  periods: () => api.get('/finance/periods'),
  closePeriod: (month) => api.post(`/finance/periods/${month}/close`),
  reopenPeriod: (month, reason) => api.post(`/finance/periods/${month}/reopen`, { reason }),
};

/**
 * Draft invoices (owner decision 9a, 2026-10-21): prepared when the customer accepts a quote,
 * edited and sent by staff. Every save, send and download names the revision it was made
 * from; the server refuses a stale one. Reading needs `financial:read`, changing
 * `financial:write`.
 */
export const invoiceDraftsApi = {
  list: (params) => api.get('/invoice-drafts', params),
  get: (id) => api.get(`/invoice-drafts/${id}`),
  forShipment: (shipmentId) => api.get(`/shipments/${shipmentId}/invoice-draft`),
  update: (id, payload) => api.patch(`/invoice-drafts/${id}`, payload),
  send: (id, expectedRevision, { acknowledgeSuperseded = false } = {}) =>
    api.post(`/invoice-drafts/${id}/send`, {
      expected_revision: expectedRevision,
      acknowledge_superseded: acknowledgeSuperseded,
    }),
  withdraw: (id, reason) => api.post(`/invoice-drafts/${id}/withdraw`, { reason }),
  downloadPdf: (id, revision) => downloadBlob(`/invoice-drafts/${id}/pdf`, { revision }),
  downloadInvoicePdf: (invoiceId) => downloadBlob(`/invoices/${invoiceId}/pdf`),
};

/**
 * RC-UAT-21 Phase D (DEC-0233), Admin only: soft delete of old quote versions (reason
 * required, restore supported) and Settings > Retention (disabled by default; only a dry run
 * can be started from the screen).
 */
export const dataRetentionApi = {
  quoteHistory: (shipmentId, includeDeleted = false) =>
    api.get(`/shipments/${shipmentId}/quote-history`, { include_deleted: includeDeleted }),
  deleteQuote: (versionId, reason) => api.post(`/quote-versions/${versionId}/delete`, { reason }),
  restoreQuote: (versionId, reason) =>
    api.post(`/quote-versions/${versionId}/restore`, { reason }),
  overview: () => api.get('/admin/data-retention'),
  updateSettings: (payload) => api.patch('/admin/data-retention/settings', payload),
  updatePolicy: (recordClass, payload) =>
    api.patch(`/admin/data-retention/policies/${recordClass}`, payload),
  dryRun: () => api.post('/admin/data-retention/dry-run'),
};

/** Milestone notifications (Phase 13F): the outbox and a customer's choices. Test capture only. */
export const notificationsApi = {
  list: (params) => api.get('/notifications', params),
  retry: (id) => api.post(`/notifications/${id}/retry`),
  preferences: (customerId) => api.get(`/customers/${customerId}/notification-preferences`),
  setPreferences: (customerId, preferences) =>
    api.patch(`/customers/${customerId}/notification-preferences`, { preferences }),
};
