# Set Ready — your own copy

Set Ready is a producer's tool for shoot days: call sheets sent to crew with
one-tap confirmations, jobs with crew dates and deal memos, rooming lists,
per diem, travel docs, and a PC log where receipts are read for you and the
job reconciles to its margin. **Plan the day. Tell the crew. Know they got
it.**

This repository is the code behind a copy you run yourself, on accounts you
own. It is deployed by the Railway template, not by hand:

**https://railway.com/deploy/YeBdBK**

If you bought Set Ready, the setup is done for you by your own Claude using
the skill in your download: upload it, say "set up Set Ready", and follow
along. You never need a terminal.

## What's here

| Directory | What |
|---|---|
| `backend/` | The API — Python, FastAPI. Builds from the root `Dockerfile` |
| `frontend/` | The app — Next.js. Builds from `frontend/Dockerfile` |
| `supabase/migrations/` | The database. `0001_baseline.sql` builds it in an empty Supabase project; later files are updates, run in order, each once |

## What it runs on

- **Railway** (both services; about $5–10 a month)
- **Supabase** (database, sign-in, files; free to start, $25 a month for backups and no pausing)
- **Anthropic** (an API key, billed per use, for reading receipts and crew lists)

## Settings

Set on the Railway services. The template asks for the ones without a default.

| Variable | Service | What |
|---|---|---|
| `SUPABASE_URL` | backend | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | backend | Your Supabase **secret** key |
| `ANTHROPIC_API_KEY` | backend | Your Anthropic API key |
| `SINGLE_OWNER` | backend | `1`: one account owns this copy; everyone else is turned away |
| `PUBLIC_URL` | backend | The frontend's address |
| `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL` | backend | Email sending; `unused` until you set it up |
| `NEXT_PUBLIC_SUPABASE_URL` | frontend | The same Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | frontend | Your Supabase **publishable** key |
| `NEXT_PUBLIC_API_URL` | frontend | The backend's address |

## Licence

See `LICENSE.md`. In short: run it and change it for your own work; don't
resell it or run it for others.
