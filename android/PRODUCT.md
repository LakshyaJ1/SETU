# SETU Navigator

<!-- impeccable:product-schema 1 -->

## Platform

android

## Users

Drivers using a mounted phone are the primary audience. Field testers and the
engineering team use recording, replay and diagnostics. Reviewers may explore an
explicitly labelled demonstration without connecting hardware.

## Product Purpose

An offline-first navigation application for journeys through unreliable GNSS.
The application owns permission handling, maps, route presentation, sensor
collection, session lifecycle, local recordings, replay and clear uncertainty.
The estimation and AI/ML components are separate from presentation.

## Positioning

SETU joins sensor-derived motion with road geometry. It must reveal which
measurements are actually available rather than cosmetically keeping a marker
moving. A moving demonstration marker is not evidence of navigation accuracy.

## Presentation MVP

The immediate delivery is an Android presentation MVP, not the complete field
release. Its core loop is live position tracking, local recording, saved-journey
replay and offline route exploration. A separate native-engine demonstration
uses explicitly simulated GPS and motion inputs to explain a short GPS gap,
uncertainty growth and reacquisition. It must never be confused with a measured
blackout trial. The walkthrough and release boundaries live in
`../docs/14-demo-mvp.md`.

## Operating Context

Navigation is glanceable and usable in daylight or at night. Detailed charts and
configuration belong to stationary testing, not active driving. Trips stay local;
export and any model-server connection require deliberate user actions.

## Capabilities and Constraints

- Navigate, Diagnostics, Drive Log, Collect and Settings are the Android scope.
- The existing Python implementation remains the scientific reference, not an
  Android runtime or a trained model.
- The teammate owns AI/ML. The Android application supplies a versioned provider
  boundary, a connection check and an honest unavailable state.
- A native sensor source is not an AI model. Device rates and missing sensors
  must be measured, not inferred from the phone name.
- Offline maps and saved-trip replay must work without a server.
- Users own their offline area selection. Imported map revisions must retain
  provenance, explicit activation, rollback and safe removal. A checksum is
  integrity evidence, not proof of current or trustworthy navigation data.
- No account, billing, social feed or cloud trajectory storage is required.
- Model-free GPS operation and synthetic replay must never be labelled as
  verified SETU dead reckoning.
- No accuracy, battery, field readiness or completion claim without appropriate
  measured evidence. Screenshots prove visible UI states, not sensor accuracy.

## Evidence on Hand

The reference implementation, simulator and tests live in `../setu/` and
`../tests/`. The intended architecture and Android screens are described in
`../docs/04-architecture.md` and `../docs/05-system-design.md`. Screenshot and
runtime verification records belong in `../docs/verification/` as they are earned.

## Product Principles

1. Location, uncertainty and next action are readable at a glance.
2. Degradation is explicit, recoverable and never disguised as success.
3. The driver does not need to understand estimator acronyms.
4. Recording and sharing are distinct decisions; local is the default.
5. Every demonstration and imported recording retains its provenance.

## Accessibility & Inclusion

Use Material 3 controls, system Back, edge-to-edge insets, scalable text,
TalkBack semantics and at least 48 dp touch targets. Supply first-class light and
dark schemes. Reduce nonessential animation with the system setting. Meaningful
state must not depend on color, gesture-only actions or charts alone.
