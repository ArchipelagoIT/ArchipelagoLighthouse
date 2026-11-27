---
name: design-kickoff
description: Agree the visual design direction for a new project or a new app before any UI code is written. Use at the start of a project, before the first screen of a new app, when docs/design-direction.md does not exist, or when the user wants to change the look.
---

# Design kickoff

Goal: an agreed `docs/design-direction.md` and `design/tokens/tokens.json` before any UI code.
Do not pick a look yourself.

## 1. Check what exists
- Read `docs/project.md` and any existing `docs/design-direction.md`, designs or screenshots.
- Skip questions those already answer.

## 2. Ask in rounds (max 3 questions per round)
Offer 2–4 concrete options per question, plus your recommendation and why.
If an answer seems wrong for the users, say so honestly.

Round 1 — who and where
1. Who uses it (guests, front office, housekeeping, managers, corporate)?
2. Where and on what device (desk monitor, phone on the move, tablet at a counter, kiosk)?
3. Guest-facing, staff-only, or both?

Round 2 — identity and mood
4. Identity: Archipelago corporate, a specific hotel brand, its own product identity, or neutral?
5. Three words for how it should feel (e.g. calm, premium, fast, playful, utilitarian).
6. Apps or sites they like or dislike the look of, and what exactly about them.

Round 3 — practical
7. Density: spacious, balanced, or compact?
8. Light, dark, or both?
9. Fixed constraints: colors, fonts or logo that must or must not be used?

Round 4 — only if relevant
10. Languages beyond English and Bahasa Indonesia?
11. Accessibility needs beyond the baseline (older users, outdoor glare)?
12. Who approves the design?

## 3. Record and propose
1. Write `docs/design-direction.md` (one page): users, context, identity, mood, references,
   density, modes, constraints, approver, date.
2. Propose 2–3 small visual directions: one key screen each, desktop and mobile.
   One or two lines on each: what it optimises for and its trade-off.
3. Wait for the user to choose (or mix).

## 4. Build the tokens
- Create `design/tokens/tokens.json` (W3C design-token format): palette, semantic tokens
  (`color.text.primary`, `color.surface.card`, `color.status.*`), typography, spacing, radius, motion.
- Check contrast of every text/background pair (≥ 4.5:1; 3:1 for large text and UI graphics).
- Check the chosen fonts' real available weights.
- Set up token generation once (the template does not include it yet):
  Style Dictionary (latest stable, pinned in `design/tokens/package.json` with a lock file) builds
  `tokens.json` into the Tailwind theme for `web/` and a Dart `ThemeExtension` for `mobile/`.
  Add a `design/tokens` step to `make gen` and a Dependabot npm entry for `/design/tokens`.
  Generated theme files are never edited by hand.
- Run `make gen` so web and mobile themes are generated.

## 5. Changing direction later
Update `design-direction.md` and the tokens first, then screens. Never patch colors screen by screen.
