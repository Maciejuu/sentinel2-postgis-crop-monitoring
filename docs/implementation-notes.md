# Portfolio preparation notes

## Changes to the supplied scripts

- Replaced four hard-coded database dictionaries with shared environment configuration.
- Removed personal absolute input paths; added repository-relative defaults.
- Added `.env.example` and `.gitignore`; no populated `.env` is distributed.
- Made psql use the same host and port as the Python connection.
- Added psql ON_ERROR_STOP and subprocess return-code checks before metadata updates.
- Added an explicit opt-in guard before table rebuild and working-directory cleanup.
- Made extraction use a fixed disposable project folder and create it if needed.
- Missing acquisition dates now return None rather than an invalid date string.
- Removed forced TkAgg selection so Matplotlib can choose an available backend.
- Database processing failures in cleanup/merge routines now stop the pipeline instead of allowing it to mark failed work as complete.

## Validation

Python syntax was checked for every packaged script. Offline checks cover missing credentials, configuration values and the destructive-import guard. No database was contacted and no original input imagery was processed. Historical figures are evidence from the report, not newly reproduced results.

## Before publishing

Upload the contents of the prepared repository folder, including `.gitignore` and `.env.example`. Do not add original scripts or the original PDF alongside the cleaned versions. Rotate the old database password if still in use; removing it from source code does not invalidate it or erase previous Git history.

The earlier NDVI-only script is included only as a reference. Start a new dedicated database with the main NDVI/NDMI workflow rather than mixing their schemas.
