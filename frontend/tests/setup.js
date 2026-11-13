import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup, configure } from '@testing-library/react';

// How long `findBy*` and `waitFor` keep looking before they give up. The library's
// default is one second, and the first test in any file that mounts the real `App` pays
// for the lazy import of a whole shell -- `AccountApp`, `PublicApp` or `StaffApp` --
// through Vite's transform on a cold worker. Under Vitest 4, with twenty-one files
// running in parallel on a OneDrive-backed checkout, that first import took just over a
// second on about one run in three, and the test failed at 1,0xx ms while the page was
// still the `app-boot` placeholder. Nothing was wrong with the page. A longer ceiling
// changes no assertion: a screen that never arrives still fails, four seconds later.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
