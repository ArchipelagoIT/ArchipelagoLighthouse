---
paths:
  - "mobile/**"
---
# Flutter mobile rules

## Stack
Stable channel; Riverpod; `go_router` (typed routes, deep links); `dio` client generated from OpenAPI; `freezed` + `json_serializable`; `flutter_secure_storage`; `intl` with ARB files; strict lints.

This stack is for Archipelago projects. Skills or rules written for Sentinel Tech apps
(for example `sentec-flutter-arch`: BLoC, AutoRoute, Retrofit) do **not** apply here; ignore them.

## Rules
- **UI only**; no business rule the backend does not also enforce.
- Feature-first: `lib/features/<feature>/{data,domain,presentation}`, shared code in `lib/core/`.
- Flavors `dev`, `staging`, `prod`, each with its own bundle/application ID, icon badge and API URL.
- Tokens only in `flutter_secure_storage`; short-lived access tokens with refresh.
- Theme from design tokens (`ThemeData` + `ThemeExtension`). No hard-coded colors or sizes in widgets.
- Respect platform behaviour: iOS back-swipe, Android back, safe areas, text scaling to 200 %.
- Staff apps tolerate weak Wi-Fi: retry, queue safe actions, show sync status.
- Ask for permissions only when needed, after a short reason screen.
- A remote "minimum supported version" check can force updates.
- No secrets or write-capable keys in the binary; assume it will be decompiled.
- Bundle fonts as subsets only (e.g. Latin) to keep the app small.
- `flutter analyze` must have zero warnings.

## Tests
- Unit, widget and golden tests with `flutter_test`; `integration_test` for key flows; semantics checks for accessibility.

## Release
- Build and sign in CI (fastlane). Signing keys live only in CI secrets; never read them.
- Internal → TestFlight / Play internal → staged rollout (10 % → 50 % → 100 %), watching crash-free rate.
- The backend stays compatible with every app version above the minimum supported version.
