/**
 * Top-bar global search (Design.md section 4).
 *
 * Results are grouped into Customers and Shipments, keyboard navigable, with an exact
 * identifier match listed first.
 *
 * Barcode scanners type the identifier and press Enter, which is why an exact Solaris
 * Shipment ID or package reference resolves straight to the record: `/shipments/lookup`
 * is an exact-only endpoint, so a scan can never fan out into other customers' shipments.
 * A package scan opens the parent shipment with that package selected.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { opsApi, shipmentsApi } from '../../api/endpoints.js';
import { useT } from '../../i18n/index.jsx';
import { P, useSession } from '../../app/SessionContext.jsx';
import { InlineSpinner } from '../state/index.jsx';

const DEBOUNCE_MS = 220;

/** A scanned identifier looks like SX-VCA-XXXXXXXXXXXX, optionally with -01. */
const REFERENCE_PATTERN = /^SX-[A-Z]{3}-[A-Z0-9]{12}(-\d{2})?$/;

export function GlobalSearch() {
  const t = useT();
  const navigate = useNavigate();
  const { can } = useSession();
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef(null);

  const canSeeShipments = can(P.SHIPMENT_READ);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [term]);

  useEffect(() => {
    function onClick(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const customerQuery = useQuery({
    queryKey: ['search', debounced],
    queryFn: () => opsApi.search(debounced, 6),
    enabled: debounced.length >= 2,
    staleTime: 15_000,
  });

  const shipmentQuery = useQuery({
    queryKey: ['search-shipments', debounced],
    queryFn: () => shipmentsApi.search(debounced, 6),
    enabled: debounced.length >= 2 && canSeeShipments,
    staleTime: 15_000,
  });

  const isFetching = customerQuery.isFetching || shipmentQuery.isFetching;

  const customers = useMemo(() => customerQuery.data?.items ?? [], [customerQuery.data]);
  const shipments = useMemo(() => shipmentQuery.data?.items ?? [], [shipmentQuery.data]);

  /** One flat list drives keyboard navigation; the render groups it again. */
  const results = useMemo(
    () => [
      ...shipments.map((item) => ({ kind: 'shipment', item })),
      ...customers.map((item) => ({ kind: 'customer', item })),
    ],
    [shipments, customers],
  );

  function goTo(result) {
    if (!result) return;
    setOpen(false);
    setTerm('');
    if (result.kind === 'shipment') {
      navigate(`/shipments/${result.item.id}`);
    } else {
      navigate(`/customers/${result.item.id}`);
    }
  }

  /**
   * A scanned package reference opens its shipment on the Packages tab.
   *
   * It used to append `&package=<id>` as well. The shipment detail screen reads `tab` and
   * nothing else, so that parameter selected nothing and only made the URL claim more
   * than the page does.
   */
  async function resolveScan(value) {
    try {
      const match = await shipmentsApi.lookup(value);
      setOpen(false);
      setTerm('');
      const suffix = match.package_id ? '?tab=packages' : '';
      navigate(`/shipments/${match.shipment_id}${suffix}`);
      return true;
    } catch {
      return false;
    }
  }

  async function onKeyDown(event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      const scanned = term.trim().toUpperCase();
      if (canSeeShipments && REFERENCE_PATTERN.test(scanned)) {
        const resolved = await resolveScan(scanned);
        if (resolved) return;
      }
      goTo(results[highlight] ?? results[0]);
      return;
    }
    if (!results.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlight((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlight((index) => (index - 1 + results.length) % results.length);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  function renderOption(result, index) {
    const selected = index === highlight;
    const common = {
      key: `${result.kind}-${result.item.id}`,
      type: 'button',
      role: 'option',
      'aria-selected': selected,
      className: 'topbar__result',
      style: selected ? { background: 'var(--surface-muted)' } : undefined,
      onMouseEnter: () => setHighlight(index),
      onClick: () => goTo(result),
    };

    if (result.kind === 'shipment') {
      const shipment = result.item;
      return (
        <button {...common}>
          <span className="mono">{shipment.public_id || t('shipments.draftNoId')}</span>
          <span>{shipment.customer?.full_name || shipment.recipient_name || '—'}</span>
          <span className="spacer" />
          <span className="meta">{t(`routes.${shipment.route_group}`, shipment.route_group)}</span>
        </button>
      );
    }

    const customer = result.item;
    return (
      <button {...common}>
        <span className="mono">{customer.public_id}</span>
        <span>{customer.full_name}</span>
        <span className="spacer" />
        <span className="meta">{customer.city || '—'}</span>
      </button>
    );
  }

  return (
    <div className="topbar__search" ref={containerRef}>
      <label className="visually-hidden" htmlFor="global-search">
        {t('customers.searchPlaceholder')}
      </label>
      <input
        id="global-search"
        type="search"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls="global-search-results"
        aria-autocomplete="list"
        autoComplete="off"
        placeholder={
          canSeeShipments ? t('shipments.searchPlaceholder') : t('customers.searchPlaceholder')
        }
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
          setHighlight(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && debounced.length >= 2 && (
        <div className="topbar__results" id="global-search-results" role="listbox">
          {isFetching && results.length === 0 && (
            <div style={{ padding: 12 }}>
              <InlineSpinner />
            </div>
          )}
          {!isFetching && results.length === 0 && (
            <p className="meta" style={{ padding: 12 }}>
              No customers or shipments match “{debounced}”.
            </p>
          )}
          {shipments.length > 0 && (
            <>
              <div className="topbar__group-label">{t('shipments.title')}</div>
              {results
                .map((result, index) => ({ result, index }))
                .filter(({ result }) => result.kind === 'shipment')
                .map(({ result, index }) => renderOption(result, index))}
            </>
          )}
          {customers.length > 0 && (
            <>
              <div className="topbar__group-label">{t('customers.title')}</div>
              {results
                .map((result, index) => ({ result, index }))
                .filter(({ result }) => result.kind === 'customer')
                .map(({ result, index }) => renderOption(result, index))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
