---
paths:
  - "web/**"
---
# Next.js web rules

## Stack
Next.js App Router, TypeScript `strict`, pnpm, Tailwind (theme generated from tokens), shadcn/ui restyled with tokens, TanStack Query, `openapi-fetch` generated client, Zod, `next-intl`, Vitest + Testing Library, Playwright, ESLint + Prettier.

## Rules
- **UI only.** No business rules, DB access or permission checks in Server Actions, Route Handlers or middleware. Route Handlers may only proxy or set the cookie the Go API returns.
- Server Components by default; `"use client"` only where interaction needs it.
- No `any`; use `unknown` and narrow.
- Call the Go API only through the generated client.
- Session in an **httpOnly, Secure, SameSite=Lax** cookie issued by Go. Never tokens in `localStorage`. Client-side role checks are for display only.
- Forms: Zod for UX validation; show server errors from Problem Details. The server always validates again.
- No hard-coded colors, sizes or fonts; no user-facing strings outside `next-intl` messages.
- No `dangerouslySetInnerHTML` without sanitising.
- Security headers: CSP with nonces, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `frame-ancestors`.
- `next/image`, `next/font`. Build with `output: "standalone"`; runs as a container on ECS.
- Performance budget for guest pages (mobile 4G): LCP < 2.5 s, INP < 200 ms, CLS < 0.1.

## Tests
- Vitest for components, hooks and forms.
- Playwright for key journeys on Chromium, WebKit and a mobile viewport, with axe accessibility checks on each main screen.
