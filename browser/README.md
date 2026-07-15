# Sophyane Browser

**AI browser shell** for Sophyane — designed for flexible agent use (search / answer / sources / tools / mesh), comparable in UX intent to modern AI browsers (e.g. Perplexity-style ask + sources), while staying open-source and installable from this repository.

## Download from GitHub

| Asset | URL |
|-------|-----|
| **This folder** | https://github.com/badrpk/sophyane/tree/main/browser |
| **Releases** | https://github.com/badrpk/sophyane/releases |
| **One-line install (Linux/macOS)** | see below |
| **Windows** | `install.ps1` |

### Quick install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/browser/install.sh | sh
sophyane-browser
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/badrpk/sophyane/main/browser/install.ps1 | iex
```

### What you get

- **Ask / Search** — big query box, AI answers, follow-ups  
- **Sources** — URL fetch + source chips when you paste links  
- **Agent tools** — platform, hardware, kernel, train status  
- **Mesh / Status** — live local APIs `:8770` / `:8777`  
- **History** — local browser history (this device)  
- **New-tab mode** — always available without Chromium:

```bash
SOPHYANE_BROWSER_MODE=tab sophyane-browser
```

### Dedicated Chromium window

Install Chromium/Chrome for an isolated profile under  
`~/.local/state/sophyane/browser-profile`.

Without Chromium, Sophyane **opens a new tab** in your default browser (feature kept).

### Package layout

```
browser/
  README.md
  install.sh
  install.ps1
  home/          # UI (also shipped inside Python package)
  package.sh     # build release tarball
```

### Build release tarball

```bash
bash browser/package.sh
# → dist/sophyane-browser-<version>.tar.gz
```

### Related

- CLI: `sophyane --browser`  
- Cloud portal: `/browser.html` download page  
- Handbook: docs + website start guide  
