/**
 * A render error inside one panel stays inside that panel (RC-UAT-25 item 7, Ben 2026-10-25).
 *
 * With no boundary anywhere, one exception while rendering a shipment tab unmounted the whole
 * staff app and left a blank page. This catches it, keeps the header and the other tabs, and
 * shows a readable message with Try again (which re-renders, after `onRetry` -- e.g. a refetch).
 * Fixing the cause is still required: this only stops one bad value blanking everything.
 */

import { Component } from 'react';
import { useT } from '../../i18n/index.jsx';
import { Button } from '../ui/index.jsx';

function PanelErrorFallback({ error, onRetry }) {
  const t = useT();
  return (
    <div className="state-block" role="alert">
      <p className="state-block__title">{t('states.panelErrorTitle')}</p>
      <p className="state-block__body">{t('states.panelErrorBody')}</p>
      {error?.message && <p className="meta mono">{String(error.message)}</p>}
      <Button onClick={onRetry}>{t('states.panelErrorRetry')}</Button>
    </div>
  );
}

export class PanelErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.retry = this.retry.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Kept in the console so a support session can still see the stack.
    console.error('Panel render failed', error, info?.componentStack);
  }

  componentDidUpdate(previous) {
    // A different panel (or record) gets a fresh start.
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  retry() {
    this.props.onRetry?.();
    this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return <PanelErrorFallback error={this.state.error} onRetry={this.retry} />;
    }
    return this.props.children;
  }
}
