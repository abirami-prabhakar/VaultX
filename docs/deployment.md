# Render preparation (not live-verified)

The tested demo runs locally. No Render service, disk, or hosted model was created or exercised. The following is a preparation guide for a controlled synthetic demonstration, not a claim of production readiness. Individual identities/roles, native-parser process isolation, distributed rate limits, backups and schema migrations remain deployment work.

Render can host [FastAPI web services](https://render.com/docs/deploy-fastapi) and [static frontends](https://render.com/docs/static-sites). Use separate services with these repository-specific commands:

| Setting | Python web service | Static frontend |
| --- | --- | --- |
| Root directory | Repository root | `frontend` |
| Build | `pip install -r backend/requirements-lock.txt` | `npm ci && npm run build` |
| Start | `uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT` | Managed static hosting |
| Publish directory | Not applicable | `dist` |
| Health path | `/health` | `/` |

Use the tested Python 3.11 family and Node 24 or 22.12+. For the backend, configure a unique private `API_KEY`, `EXTRACTION_MODE=demo`, `OCR_ENABLED=false`, and `PROMPT_GUARD_ENABLED=false`. Set `FRONTEND_ORIGINS` to the exact HTTPS frontend origin. Keep a single backend instance/worker for this SQLite demonstration.

Set frontend `VITE_API_BASE_URL` to the complete HTTPS backend origin **without `/api`**, because backend routes are rooted at `/instruments`, `/dashboard`, etc. Do not set a frontend reviewer credential. Production builds omit `VITE_API_KEY` and prompt for the backend key at runtime. Share that key privately with authorized demo reviewers. Hash-based frontend navigation needs no additional SPA rewrite.

Persistent SQLite and original documents need a [persistent disk](https://render.com/docs/disks), which Render currently supports on paid services. For a disk mounted at `/var/data`, use:

```dotenv
DATABASE_URL=sqlite:////var/data/vaultx.db
STORAGE_DIR=/var/data/documents
```

Without that disk, Render's ephemeral filesystem loses records and documents on restart/redeploy. A disk is available at runtime, not during builds. Persistent disks prevent multiple service instances; take database-consistent backups separately. The process-local IP budget can group clients behind Render's proxy and is not a distributed abuse control.

After deployment, verify keyless `/instruments` returns 401, explicitly connect with the private key, upload the five canonical synthetic receipts in order, inspect evidence/findings, make a reasoned review decision, and confirm persistence across a restart. Test the hosted CORS and key flow before inviting reviewers. Do not upload operational financial data to this prototype.

Gemma/OCR hosting is separate. `gemma4:e2b` needs an independently running compatible endpoint and sufficient memory; a loopback Ollama URL on your laptop is not reachable from Render. Keep backend model credentials in server environment variables and verify actual inference before describing the demo as AI-powered.
