# Alpha50X maintenance

The application source is inside the verified code-only updater in `downloads`,
not laid out at the repository root. `tools/windows_public_validation.py` selects
the current updater and executable. Use its `load(...).unpack_payload()` helper to
restore code into an owned directory under `/workspace`; verify the updater against
`downloads/SHA256SUMS.txt` first. Inspect the restored source before editing.

Published packages contain no customer database or credentials. Keep the original
seed checksum in the embedded manifest. Development/CI ledgers are synthetic and
belong only in isolated test directories; never publish them or use them to replace
an existing installation's portfolio.

For the scroll hotfix, `tools/repack_scroll_update.py --source <directory>` repacks
the verified 5.5 updater with the explicitly allowed UI files. The existing Python
installer handles checksums, backup, validation, rollback and ledger preservation.
`tools/build_windows_setup.py --go <compiler>` builds the Windows executable and
runs bootstrap tests. Use the official Go compiler pinned in the CI workflow;
check its version rather than assuming a program named `go` is that compiler.

Install the restored `requirements.txt` in an isolated Python venv. The browser
regression is `tools/browser_smoke.py` with `PYTHONPATH` pointing to restored code.
Set `ALPHA50X_BROWSER_STRESS=1`, `ALPHA50X_BROWSER_CRYPTO_COUNT=1200` and
`ALPHA50X_BROWSER_SCROLL_CHECK=1` for the 1860-asset scrollbar check. It uses
synthetic observations and tests actual scroll movement and bounded panel height.
`--extract` in the Windows validation helper creates an isolated synthetic seed for
the full test suite; it is not an application setup procedure for a customer.

Native Windows CI tests Python 3.12/3.14, the executable checksum, bootstrap locks,
the application suite, browser layout and synthetic installation. Read reports
from the `alpha50x-validation` branch, matching both commit and executable SHA-256.
Stage reviewed source/build helpers and public downloads explicitly.

Prepared 5.6 activity work uses `tools/repack_crypto_activity_update.py`, based on
the verified 5.5.1 updater and an explicit source whitelist. The UI-only scroll
repacker remains unchanged. `tools/build_windows_setup.py --version 5_6` selects
the new package; `--version 5_5_1` still selects the previous one. The embedded
temporary filename is version independent. The native CI helper and workflow now
target 5.6; read the matching report before claiming Windows validation. The plain
source diff is `downloads/CRYPTO_ACTIVITY_5_6.patch`. Current local validation is
recorded separately; no Windows result is implied by cross-compilation.
