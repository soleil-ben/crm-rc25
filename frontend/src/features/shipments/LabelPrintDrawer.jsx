/**
 * Label preview and printing (Design.md section 10).
 *
 * Package selection on the left, an exact-ratio 4 × 6 portrait preview on the right.
 *
 * The preview is a simplified rendering: it shows the same content in the same order, so
 * staff can confirm they are about to print the right parcel, but the generated PDF is
 * the authority on dimensions, barcode module width, and scan quality. The screen deliberately
 * does not draw a barcode, because a screen barcode would invite scanning something that
 * was never validated for it.
 *
 * "Download PDF" and "Print" both fetch the real PDF from the server. Nothing here claims
 * a physical printer produced anything.
 */

import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { shipmentsApi } from '../../api/endpoints.js';
import { downloadUrl } from '../../api/client.js';
import { useT } from '../../i18n/index.jsx';
import { Banner, Button, Checkbox, Drawer } from '../../components/ui/index.jsx';
import { EmptyState, ErrorState, SkeletonRows } from '../../components/state/index.jsx';
import { formatDateTime } from '../../utils/format.js';
import './shipments.css';

function labelUrl(shipmentId, packageIds) {
  return downloadUrl(`/shipments/${shipmentId}/labels.pdf`, {
    package_id: packageIds.length ? packageIds : undefined,
  });
}

/** One 4 × 6 page at the exact 2:3 aspect ratio, scaled to fit the drawer. */
function LabelPreviewCard({ label }) {
  const t = useT();
  return (
    <div className="label-preview" role="img" aria-label={`${label.package_reference} label preview`}>
      <div className="label-preview__header">
        <span className="label-preview__wordmark">{label.wordmark}</span>
        <span className="label-preview__route">{label.route_code}</span>
      </div>
      <div className="label-preview__route-name">
        {label.route_name}
        {label.direction_label ? ` · ${label.direction_label}` : ''}
      </div>
      <hr className="label-preview__rule" />

      <div className="label-preview__caption">{t('booking.solarisId').toUpperCase()}</div>
      <div className="label-preview__id mono">{label.shipment_public_id}</div>

      <div className="label-preview__row">
        <span className="label-preview__caption">
          {t('booking.packageReferences').toUpperCase()}
        </span>
        <span className="label-preview__caption">{label.position_label.toUpperCase()}</span>
      </div>
      <div className="label-preview__reference mono">{label.package_reference}</div>

      {/* A placeholder, not a barcode: only the PDF carries a scannable symbol. */}
      <div className="label-preview__barcode" aria-hidden="true">
        <span>Code 128 · {label.package_reference}</span>
      </div>

      <hr className="label-preview__rule" />
      <div className="label-preview__caption">{t('labels.deliverTo').toUpperCase()}</div>
      <div className="label-preview__recipient">{label.recipient_name}</div>
      {label.destination_lines.map((line) => (
        <div key={line} className="label-preview__destination">
          {line}
        </div>
      ))}

      <div className="label-preview__footer-grid">
        <div>
          <div className="label-preview__caption">BOOKED</div>
          <div className="label-preview__value">{label.booking_date}</div>
          {label.weight_display && (
            <>
              <div className="label-preview__caption">GROSS WEIGHT</div>
              <div className="label-preview__value">{label.weight_display}</div>
            </>
          )}
          {label.warehouse_location && (
            <>
              <div className="label-preview__caption">LOCATION</div>
              <div className="label-preview__value">{label.warehouse_location}</div>
            </>
          )}
          {label.handling_note && (
            <>
              <div className="label-preview__caption">HANDLING</div>
              <div className="label-preview__value">{label.handling_note}</div>
            </>
          )}
        </div>
        <div className="label-preview__qr" aria-hidden="true">
          <span>QR</span>
          <span className="label-preview__qr-caption">{t('labels.scanToTrack')}</span>
        </div>
      </div>

      <div className="label-preview__warning">{label.warning}</div>
    </div>
  );
}

export function LabelPrintDrawer({ open, onClose, shipmentId }) {
  const t = useT();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState([]);
  const [previewIndex, setPreviewIndex] = useState(0);

  const previewQuery = useQuery({
    queryKey: ['label-preview', shipmentId],
    queryFn: () => shipmentsApi.labelPreview(shipmentId),
    enabled: open && Boolean(shipmentId),
  });

  const historyQuery = useQuery({
    queryKey: ['label-jobs', shipmentId],
    queryFn: () => shipmentsApi.labelJobs(shipmentId),
    enabled: open && Boolean(shipmentId),
  });

  const labels = useMemo(() => previewQuery.data?.labels ?? [], [previewQuery.data]);

  useEffect(() => {
    if (labels.length) setSelected(labels.map((label) => label.package_id));
  }, [labels]);

  const allSelected = labels.length > 0 && selected.length === labels.length;
  const chosen = allSelected ? [] : selected;
  const hasHistory = (historyQuery.data ?? []).length > 0;

  function toggle(packageId) {
    setSelected((current) =>
      current.includes(packageId)
        ? current.filter((item) => item !== packageId)
        : [...current, packageId],
    );
  }

  function afterGeneration() {
    // The server records every generation, so the history list is refetched.
    queryClient.invalidateQueries({ queryKey: ['label-jobs', shipmentId] });
  }

  function download() {
    window.location.href = labelUrl(shipmentId, chosen);
    setTimeout(afterGeneration, 800);
  }

  function print() {
    // Open the real PDF; the browser's own print dialog handles actual-size printing.
    window.open(labelUrl(shipmentId, chosen), '_blank', 'noopener');
    setTimeout(afterGeneration, 800);
  }

  const activePreview = labels[Math.min(previewIndex, Math.max(labels.length - 1, 0))];

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('labels.title')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.close')}</Button>
          <span className="spacer" />
          <Button onClick={print} disabled={!labels.length || selected.length === 0}>
            {hasHistory ? t('labels.reprint') : t('labels.print')}
          </Button>
          <Button
            variant="primary"
            onClick={download}
            disabled={!labels.length || selected.length === 0}
          >
            {t('labels.download')}
          </Button>
        </>
      }
    >
      {previewQuery.isLoading && <SkeletonRows rows={4} />}
      {previewQuery.error && <ErrorState error={previewQuery.error} onRetry={previewQuery.refetch} />}

      {previewQuery.data && labels.length === 0 && (
        <EmptyState title={t('labels.noActivePackages')} body={t('labels.draftNote')} />
      )}

      {labels.length > 0 && (
        <div className="label-drawer">
          <div className="label-drawer__selection">
            <h3 className="card__title">{t('labels.selectPackages')}</h3>
            <Checkbox
              label={t('labels.selectAll')}
              checked={allSelected}
              onChange={(event) =>
                setSelected(event.target.checked ? labels.map((item) => item.package_id) : [])
              }
            />
            <ul className="label-drawer__packages">
              {labels.map((label, index) => (
                <li key={label.package_id}>
                  <Checkbox
                    label={
                      <span>
                        <span className="mono">{label.package_reference}</span>
                        <span className="meta"> — {label.position_label}</span>
                      </span>
                    }
                    checked={selected.includes(label.package_id)}
                    onChange={() => toggle(label.package_id)}
                  />
                  <Button
                    compact
                    variant="tertiary"
                    onClick={() => setPreviewIndex(index)}
                    aria-pressed={index === previewIndex}
                  >
                    {t('labels.preview')}
                  </Button>
                </li>
              ))}
            </ul>

            <Banner tone="warning" title={t('labels.actualSize')}>
              {t('labels.actualSizeInstruction')}
            </Banner>
            <p className="meta">{t('labels.internalOnly')}</p>
            <p className="meta">{t('labels.generationNote')}</p>
            <p className="meta">
              {t('labels.trackingBase')}:{' '}
              <span className="mono">{previewQuery.data.tracking_base_url}</span>
            </p>

            <h3 className="card__title">{t('labels.history')}</h3>
            {!hasHistory && <p className="meta">{t('labels.historyEmpty')}</p>}
            {hasHistory && (
              <ul className="label-drawer__history">
                {historyQuery.data.map((job) => (
                  <li key={job.id}>
                    <span>{formatDateTime(job.generated_at)}</span>
                    <span className="meta">
                      {job.page_count} {t('labels.pages')}
                      {job.is_reprint ? ` · ${t('labels.isReprint')}` : ''}
                      {job.generated_by ? ` · ${job.generated_by.full_name}` : ''}
                    </span>
                    <span className="meta mono">{job.package_references.join(', ')}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="label-drawer__preview">
            <p className="meta">{t('labels.previewNote')}</p>
            {activePreview && <LabelPreviewCard label={activePreview} />}
          </div>
        </div>
      )}
    </Drawer>
  );
}
