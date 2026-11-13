import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { captureLinkToken } from './account/linkToken.js';
import { App } from './app/App.jsx';

// Before anything renders and before the router reads the location: a verification or
// password-reset token arriving in the URL fragment is moved into memory and stripped
// from the address bar (CA-SEC-07). A no-op on every other URL.
captureLinkToken();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
