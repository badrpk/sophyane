# Authentication (all products)

## Features
- **Sign up** — email + password (min 6) → OTP to verify
- **Sign in** — email + password
  - **Existing verified users: NO OTP**
  - New/unverified users: OTP required once
- **OTP** — 6-digit, 10 minutes; emailed via SMTP when configured (else `demo_code` in response)
- **Google / Gmail OAuth** — `POST /auth/oauth/google` with `id_token` or demo `profile`
- **Facebook OAuth** — `POST /auth/oauth/facebook` with `access_token` or demo `profile`
- Social login **always skips OTP** (provider-trusted identity)

## Routes
| Method | Path | Body |
|--------|------|------|
| POST | `/auth/signup` | `{email, password, name?}` |
| POST | `/auth/login` | `{email, password}` |
| POST | `/auth/otp/request` | `{email, purpose?}` |
| POST | `/auth/otp/verify` | `{email, code}` |
| POST | `/auth/oauth/google` | `{id_token}` or `{profile:{email,name,id}}` |
| POST | `/auth/oauth/facebook` | `{access_token}` or `{profile:{email,name,id}}` |
| GET | `/auth/me` | Header `Authorization: Bearer <token>` |
| POST | `/auth/logout` | token header or body |
| GET | `/auth/capabilities` | — |

## Config (optional)
`~/.config/sophyane/auth.env` / `oauth.env`:
```
GOOGLE_CLIENT_ID=...
FACEBOOK_APP_ID=...
AUTH_DEMO_OAUTH=true
```
SMTP from `~/.shmry_email.env` for real OTP email.
