/**
 * Where the backend's virtual-environment interpreter lives, on either platform.
 *
 * A `venv` puts its interpreter at `Scripts/python.exe` on Windows and at `bin/python`
 * everywhere else. Three files spawn that interpreter -- the end-to-end orchestrator,
 * the seeded-reference fixture and the staff-action helper -- and until this module
 * existed two of them hard-coded the Windows path, so the suite could only run on the
 * machine it was written on. One resolution, imported by all three, keeps them agreeing.
 *
 * Paths are derived from this file's own location rather than from `process.cwd()`, so
 * the answer is the same whether the caller is Playwright (whose working directory is
 * `frontend/`) or a script started from the repository root.
 */

import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

export const WINDOWS = process.platform === 'win32';
export const FRONTEND_ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
export const REPO_ROOT = resolve(FRONTEND_ROOT, '..');

/** Repository-relative, for messages that tell a person what to type. */
export const PYTHON_RELATIVE = WINDOWS
  ? 'backend/.venv/Scripts/python.exe'
  : 'backend/.venv/bin/python';

/** Absolute, for `spawn` and `execFileSync`. */
export const PYTHON = join(REPO_ROOT, ...PYTHON_RELATIVE.split('/'));
