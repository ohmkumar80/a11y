# ADR 0010: Two-step verification for administrators

- **Status:** Accepted
- **Date:** 2026-11-27

## Decisions
- **TOTP (RFC 6238) plus one-time recovery codes**, standard library only (checked against the RFC's test vectors). A code
  is accepted once (the matched time step is stored; only a later step works next time) with one step of clock drift.
  Recovery codes: 10, shown once, stored hashed, each single-use.
- **Admin-configurable policy**, setting `auth.mfa` (versioned, audited, rollback-able, high-risk): per group
  (platform administrators, organisation administrators) one of `required` (enrol, then a code at every sign-in),
  `optional` (only people who enrolled are asked) or `off` (nobody is asked). The starting value comes from
  `MFA_SUPER_ADMIN_DEFAULT` / `MFA_ORG_ADMIN_DEFAULT`: development starts with **off** so MFA does not get in the way while
  building, and the Security tab in `/admin` flips it at runtime. Standard members are never asked.
- **Off is development-only.** For platform administrators it is refused in production at three levels: the setting's
  guard, the environment default, and the sign-in check (a stored "off" is treated as "required"). While it is off, every
  admin screen shows a banner.
- **Sign-in is two requests.** After a correct password the API returns an MFA challenge token (audience `mfa`, 10 minutes,
  stated on screen) instead of a session; `decode_access_token` rejects it, so a half-finished sign-in can never be used as
  a session. Wrong password never reaches the second step.
- **Abuse limits:** 5 wrong codes lock the account for 15 minutes (the correct code is refused while locked); failures,
  lockouts, enrolment, recovery use and disabling are audit-logged; secrets are encrypted at rest.
- **Accessible enrolment:** the setup key is shown as text, read out in groups, with a link that opens the authenticator
  app. A QR code is never the only way (it excludes blind and low-vision people). Code fields allow paste and
  `autocomplete="one-time-code"` (WCAG 3.3.8).
- **Break-glass:** `python -m a11y_api.admin_cli --reset-mfa EMAIL` (lost authenticator and recovery codes) and
  `--mfa-super-admin off|optional|required` (the latter refuses `off` in production).
- **Users table holds the MFA state** (columns, not a new table) so the existing row-level-security and pre-login lookup
  rules apply unchanged, including for Super Admins who have no tenant.

## Not done
WebAuthn/passkeys (the plan's preferred second factor for later); SMS/email codes (deliberately not offered: weaker);
a platform-admin session refresh (Super Admin sessions are still 15 minutes with no refresh, which makes MFA more
noticeable); revoking existing organisation-admin sessions when their policy becomes `required`; trusted-device
"remember me for 30 days".
