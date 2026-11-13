/**
 * Route table.
 *
 * Reports and the customer import arrived in Phase 5A, so both are real pages now and the
 * "not built yet" placeholder that stood in for Reports is gone. Nothing here is an empty
 * feature page: a route exists only when the feature behind it does (DEC-0024).
 */

import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell, PageHeader } from '../components/layout/AppShell.jsx';
import { Card } from '../components/ui/index.jsx';
import { EmptyState } from '../components/state/index.jsx';
import { useT } from '../i18n/index.jsx';
import { DashboardPage } from '../features/dashboard/DashboardPage.jsx';
import { CustomerListPage, CustomerNewPage } from '../features/customers/CustomerListPage.jsx';
import { CustomerProfilePage } from '../features/customers/CustomerProfilePage.jsx';
import { SegmentsPage } from '../features/segments/SegmentsPage.jsx';
import { FollowUpsPage } from '../features/followups/FollowUpsPage.jsx';
import { SettingsPage } from '../features/settings/SettingsPage.jsx';
import { ShipmentListPage } from '../features/shipments/ShipmentListPage.jsx';
import { ShipmentDetailPage } from '../features/shipments/ShipmentDetailPage.jsx';
import { BookingWizardPage } from '../features/shipments/BookingWizardPage.jsx';
import { ReportsPage } from '../features/reports/ReportsPage.jsx';
import { WorkspaceListPage } from '../features/workspace/WorkspaceListPage.jsx';
import { WorkspacePage } from '../features/workspace/WorkspacePage.jsx';
import { QuotePrintPage } from '../features/workspace/QuotePrintPage.jsx';
import { FinancePage } from '../features/finance/FinancePage.jsx';
import { InvoicePage } from '../features/finance/InvoicePage.jsx';
import { InvoiceDraftPage } from '../features/finance/InvoiceDraftPage.jsx';
import { InvoicePrintPage, ReceiptPrintPage } from '../features/finance/PrintPages.jsx';
import { CustomerImportPage } from '../features/imports/CustomerImportPage.jsx';
import {
  LegacyHistoryImportPage,
  ShipmentImportPage,
} from '../features/imports/BulkImportPage.jsx';
import { CustomerAccountQueuePage } from '../features/customer_accounts/CustomerAccountQueuePage.jsx';
import { ChangePasswordPage } from '../features/auth/ChangePasswordPage.jsx';
import { CustomerAccountReviewPage } from '../features/customer_accounts/CustomerAccountReviewPage.jsx';
import { ProfileChangeReviewPage } from '../features/customer_accounts/ProfileChangeReviewPage.jsx';

function NotFoundPage() {
  const t = useT();
  return (
    <>
      <PageHeader title={t('states.notFoundTitle')} />
      <Card>
        <EmptyState title={t('states.notFoundTitle')} body={t('states.notFoundBody')} />
      </Card>
    </>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="customers" element={<CustomerListPage />} />
        <Route path="customers/import" element={<CustomerImportPage />} />
        {/* RC-UAT-21 Phase A: shipment import and the legacy history baseline. */}
        <Route path="customers/import/shipments" element={<ShipmentImportPage />} />
        <Route path="customers/import/legacy" element={<LegacyHistoryImportPage />} />
        {/* Before `:customerId`, so "new" is a screen and not a customer id the API is
            asked to parse (fix pack item 11). */}
        <Route path="customers/new" element={<CustomerNewPage />} />
        <Route path="customers/:customerId" element={<CustomerProfilePage />} />
        {/* Phase 12. The screens for the Phase 10 approval API. Guarded server-side by
            `customer_account:review`; the navigation entry is hidden for a role that
            does not hold it, and the route is here for a deep link from an email or a
            bookmark, which the API refuses on its own. */}
        <Route path="customer-accounts" element={<CustomerAccountQueuePage />} />
        <Route
          path="customer-accounts/:accountReference"
          element={<CustomerAccountReviewPage />}
        />
        {/* Fix pack 2: a linked customer's name, phone or pickup-address change. */}
        <Route
          path="customer-accounts/:accountReference/profile-change"
          element={<ProfileChangeReviewPage />}
        />
        <Route path="segments" element={<SegmentsPage />} />
        <Route path="shipments" element={<ShipmentListPage />} />
        <Route path="shipments/new" element={<BookingWizardPage />} />
        <Route path="shipments/:shipmentId" element={<ShipmentDetailPage />} />
        {/* Phase 13D: the unified workspace, one master consolidation at a time. */}
        <Route path="workspace" element={<WorkspaceListPage />} />
        <Route path="workspace/:consolidationId" element={<WorkspacePage />} />
        {/* Phase 14: the printable customer quote of a finalised version (revenue only). */}
        <Route
          path="workspace/quotes/:shipmentId/:version/print"
          element={<QuotePrintPage />}
        />
        {/* Phase 13E: finance. Print pages are customer documents built from allowlists. */}
        <Route path="finance" element={<FinancePage />} />
        <Route path="finance/invoices/:invoiceId" element={<InvoicePage />} />
        <Route path="finance/invoice-drafts/:draftId" element={<InvoiceDraftPage />} />
        <Route path="finance/invoices/:invoiceId/print" element={<InvoicePrintPage />} />
        <Route path="finance/receipts/:paymentId/print" element={<ReceiptPrintPage />} />
        <Route path="follow-ups" element={<FollowUpsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        {/* RC-UAT-21 Phase B (DEC-0231): the signed-in staff member's own password. */}
        <Route path="my-password" element={<ChangePasswordPage />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
