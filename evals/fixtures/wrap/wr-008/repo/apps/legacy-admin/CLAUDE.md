# legacy-admin

This is the internal admin console, a Next.js 13 app kept on pages router
until the new admin (apps/admin/) replaces it.

## Stack
- Next.js 13 (pages router, not app router)
- React 18, TanStack Table v8
- Auth via the shared next-auth config in packages/auth

## Key Conventions
- Pages live under src/pages/; no app/ directory in this app.
- API calls go through packages/api-client; no direct fetch() in components.
- Feature flags are read from the LaunchDarkly SDK in src/flags.ts.

## Gotchas
- This app is scheduled for sunset in Q3 2026. Do not add new features here
  without explicit approval. Bug fixes only.
- The LaunchDarkly SDK version is pinned at 3.2.0 for compatibility with the
  pages router; upgrading breaks SSR.
