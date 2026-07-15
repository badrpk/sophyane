# Sophyane Browser + web intel + recursive self-improvement

## Sophyane Browser (Chromium-based)

On install (graphical sessions), Sophyane launches a **browser shell**:

- Uses **system Chromium / Chrome / Brave / Edge** when installed
- Isolated profile: `~/.local/state/sophyane/browser-profile`
- Home UI served locally with mesh + hardware status, fetch, chat, learn

```bash
sophyane-browser
# or
sophyane --browser
```

Install Chromium for the full app-window experience:
- Debian/Ubuntu: `sudo apt install chromium`
- Fedora: `sudo dnf install chromium`
- macOS: install Chrome/Chromium
- Windows: install Chrome/Edge

If Chromium is missing, Sophyane opens the default OS browser to the home UI.

## Internet + scraping

```bash
sophyane --fetch https://example.com
sophyane --learn https://example.com   # scrape + ledger proposal
```

Safety:
- Only `http`/`https`
- Blocks localhost/metadata hosts
- Stores scrapes under `~/.local/state/sophyane/web_scrape`

## Recursive self-improvement (blockchain-style)

Each insight is a **hash-linked block** on an append-only chain:

```bash
sophyane --improve-propose "title" --improve-body "details"
sophyane --improve-status
sophyane --improve-export    # daily epoch JSON + CATALOG.md
```

- Local chain: `~/.local/state/sophyane/improvement_chain.jsonl`
- Daily epochs: `improvements/epoch-YYYY-MM-DD.json`
- Catalog: `improvements/CATALOG.md`

### Daily GitHub updates

GitHub Actions workflow `.github/workflows/sophyane-daily-improve.yml` runs **once per day**,
exports an epoch, and commits the catalog.

**Security policy:** field devices contribute *proposals* and catalog epochs.
They do **not** auto-merge arbitrary executable code into Sophyane runtime without review
(that would be a supply-chain attack). Mesh devices can sync epochs; CI publishes the daily chain.

## Flow

```
Browser / CLI ──fetch/scrape──► web_intel
       │                            │
       │                            ▼
       └──chat/API────────► improvement ledger (hash chain)
                                   │
                          daily epoch export
                                   │
                          GitHub improvements/ (daily)
```
