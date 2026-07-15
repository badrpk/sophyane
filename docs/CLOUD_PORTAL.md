# Sophyane Cloud Portal — website + ultra-low API tokens

## What you get

- Investor-grade marketing site (`website/`)
- Public API signup → `sph_…` keys
- Ultra-low plans (free / $1 builder / hybrid edge)
- Hybrid model: cheap cloud + **free extra compute on user devices**
- Namecheap automation: pick domain with **longest expiry**, set A/AAAA to your static IP

## Credentials (Namecheap)

Create `~/.config/sophyane/namecheap.env` (mode 600):

```bash
NAMECHEAP_API_USER=your_api_user
NAMECHEAP_API_KEY=your_api_key
NAMECHEAP_USERNAME=your_username   # usually same as ApiUser
NAMECHEAP_CLIENT_IP=YOUR_PUBLIC_IP # must be whitelisted in Namecheap → Profile → Tools → API Access
STATIC_IPV4=x.x.x.x
STATIC_IPV6=                    # optional
```

Whitelist your public IP in Namecheap before calling the API.

## Commands

```bash
# List domains
sophyane --namecheap-domains

# Domain with longest renew/expiry
sophyane --namecheap-longest

# Point DNS at static IP (A for @, www, api, sophyane)
sophyane --namecheap-setup-site --static-ipv4 x.x.x.x

# Serve website + API
sophyane --cloud-serve --cloud-port 8780
```

## Public install path (users)

```bash
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
```

## API

```bash
curl -s http://127.0.0.1:8780/api/v1/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@example.com","plan":"hybrid"}'

curl -s http://127.0.0.1:8780/api/v1/chat \
  -H "Authorization: Bearer sph_..." \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello","edge":true}'
```

## Reverse proxy

See `website/Caddyfile.sophyane-cloud`. Point domain to your static IP, then reverse_proxy to `:8780`.
Do **not** enable basic_auth on the public portal (old `sophyane.nifdu.com` block had basic_auth for private demos only).
