/**
 * The workspace's card (owner review, 2026-11-05; DEC-0273): the same markup as the shared
 * `Card`, plus an optional show / hide toggle so a long master reads as a short list of
 * headings. A collapsed card keeps a one-line summary beside its title.
 *
 * `WorkspaceExpandProvider` broadcasts "expand all" / "collapse all" to every collapsible
 * card under it. Workspace-only: the shared `Card` is not changed.
 */

import { createContext, useContext, useEffect, useId, useState } from 'react';
import { useT } from '../../i18n/index.jsx';

const ExpandContext = createContext({ signal: null });

export function WorkspaceExpandProvider({ children }) {
  const [signal, setSignal] = useState(null);
  return (
    <ExpandContext.Provider
      value={{
        signal,
        expandAll: () => setSignal((s) => ({ open: true, n: (s?.n ?? 0) + 1 })),
        collapseAll: () => setSignal((s) => ({ open: false, n: (s?.n ?? 0) + 1 })),
      }}
    >
      {children}
    </ExpandContext.Provider>
  );
}

export function useWorkspaceExpand() {
  return useContext(ExpandContext);
}

export function CollapsibleCard({
  title,
  actions,
  children,
  flush = false,
  headingLevel: Heading = 'h2',
  collapsible = false,
  defaultOpen = true,
  summary = null,
  className = '',
}) {
  const t = useT();
  const generatedId = useId();
  const titleId = title ? `${generatedId}-title` : undefined;
  const bodyId = `${generatedId}-body`;
  const [open, setOpen] = useState(defaultOpen);
  const { signal } = useContext(ExpandContext);
  useEffect(() => {
    if (collapsible && signal) setOpen(signal.open);
  }, [collapsible, signal]);
  const shown = !collapsible || open;

  return (
    <section
      className={`card ${collapsible ? 'ws-collapsible' : ''} ${shown ? '' : 'is-collapsed'} ${className}`.trim()}
      aria-labelledby={titleId}
    >
      {(title || actions) && (
        <header className="card__header">
          {collapsible && (
            <button
              type="button"
              className="ws-toggle"
              aria-expanded={shown}
              aria-controls={bodyId}
              onClick={() => setOpen((o) => !o)}
            >
              <span aria-hidden="true" className="ws-toggle__chevron">
                {shown ? '▾' : '▸'}
              </span>
              <span className="visually-hidden">{shown ? t('wsFlow.hide') : t('wsFlow.show')}</span>
            </button>
          )}
          {title && (
            <Heading className="card__title" id={titleId}>
              {title}
            </Heading>
          )}
          {collapsible && !shown && summary && <span className="ws-summary meta">{summary}</span>}
          <span className="spacer" />
          {shown && actions}
        </header>
      )}
      <div id={bodyId} hidden={!shown} className={flush ? 'card__body card__body--flush' : 'card__body'}>
        {children}
      </div>
    </section>
  );
}
