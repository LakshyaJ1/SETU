# SETU Android Design

## Overview

**The daylight instrument.** A full geographic map, precise green route ink and
native Material controls. The interface feels like a thoughtfully made travel
instrument, not a miniature analytics dashboard. It inherits SETU's green series
identity, not the report's mandatory dark background or desktop density.

This is the Android implementation brief. It does not replace the existing HTML
report theme. The implemented colors and type roles are exercised in emulator
captures; physical-device and TalkBack validation remain separate requirements.

## Colors

| Material role | Light | Dark |
|---|---|---|
| primary | `#195A40` | `#AFDCA0` |
| onPrimary | `#FFFFFF` | `#103723` |
| primaryContainer | `#DDEDC8` | `#284F37` |
| onPrimaryContainer | `#183521` | `#E0F2CD` |
| background | `#F4F6F2` | `#101B16` |
| surface | `#FCFDF9` | `#16221B` |
| surfaceContainer | `#EAF0E6` | `#213126` |
| onSurface | `#202A23` | `#EDF3E9` |
| onSurfaceVariant | `#5F6E62` | `#B8C6B8` |
| outline | `#78877A` | `#829482` |
| error | `#AE3531` | `#FFB4AA` |

Leaf-green is action and route ink. Pale lime is a selected or informational
surface, never small text on white. An explicit source label marks replay or
limited capability; source identity never relies on color. Green never implies
an unconnected model is healthy.

Live tracking adds a blue observed-position trail (`#176C96` by day,
`#80CAEF` at night). Panning interrupts camera following; the location control
resumes it. The tracking sheet keeps the selected source, coordinates, speed and
uncertainty explicit, including stale observations and missing values.

The presentation demo uses green for the simulated reference, blue for the
native estimate and amber for the last GPS sample. A persistent simulated-input
label and a text legend carry those meanings independently of color. Lock,
GPS loss and Recovery controls provide reproducible presentation moments.

## Typography

Use the native sans through Material's named type roles. Display is 34 sp / 38 sp,
headlines 26 sp / 32 sp, titles 18 sp / 24 sp, body 16 sp / 24 sp and labels 12-14 sp.
Numerical readings use tabular figures where available. Text must survive 200%
font scaling without clipping an essential control. The SETU wordmark is compact,
bold and paired with the bridge symbol; no decorative monospace interface.

## Layout

- Compact devices use a map-first canvas, a task sheet and a labelled navigation
  bar. Drive, Record, Trips and Settings are persistent destinations. Diagnostics
  is reachable directly from status and recording, not buried in Settings.
- The top inset belongs to system status. Floating controls remain clear of
  cutouts, system gestures, attribution and the bottom sheet.
- Use a 4 dp scale: 8 within a group, 16 between related elements, 24 at screen
  edges and 32 between major sections. Do not nest decorative cards.
- Active guidance gives priority to the next maneuver, distance and location
  confidence; advanced analysis stays out of this view.
- Landscape and expanded screens put the task pane beside the map. Long content
  scrolls rather than shrinking text or hiding controls.
- Start/Stop recording stays in a persistent action area above navigation; the
  optional name, readiness readings and explanatory copy scroll independently.

## Elevation & Depth

Use Material tonal elevation. The map is the floor, the task sheet is the main
surface and dialogs are reserved for destructive or permission-related decisions.
No neon halos, decorative blur, fake glass or stacked shadowed cards.

## Shapes

The main sheet has a generous 28 dp top radius. Utility panels use 16 dp. Rounded
48 dp controls and Material chips are functional touch targets, not ornaments.
Map markers have a contrasting edge. A directional marker requires a reported
course over ground; an unknown course or stale live observation uses a dot, not
a north-facing arrow. Android's accuracy radius appears only when supplied and
fresh. It is a geographic measurement, not a decorative glow or filter confidence.
Mock-provider locations retain a visible test label, including when stale.

Native positioning is an explicit preview opt-in in live tracking and Diagnostics. Its live
heading/GPS/IMU prerequisites, accepted/gated fixes, delayed corrections, resets
and model-derived 95% radius stay visible. The map names its selected source:
GPS + IMU, inertial estimate, or GPS fallback. Native radius is not relabelled as
Android's 68% GPS accuracy. The default remains GPS; unavailable native output
never freezes into a current-looking direction marker.

Three-button system navigation uses the daylight-neutral `#F4F6F2` backplate with
dark system icons, including in dark mode. This is a platform contrast safeguard,
not a second app theme; gesture navigation follows the app theme separately.

## Components

- Search names the task: **Where to?** Results include local area and offline
  availability. Selecting a destination opens a route preview before starting.
- A status capsule uses an icon and words: GPS, Waiting for location, Replay or
  Limited positioning. A model connection has its own independent state.
- A route preview presents destination, measured route distance, map coverage and
  one Start drive action. Estimates identify their assumptions. The route origin
  is labelled as GPS, preview, demo or recording; both endpoints remain distinct.
- A recording control clearly separates Start, Stop and Save. The persistent
  Android notification exposes Stop while background collection is active.
- Empty trip history invites recording or an explicitly synthetic sample replay.
- Diagnostics show sensor presence, achieved rate and actual last measurements.
  Unavailable AI outputs show a reason and never receive fabricated numbers.
- Forms use native switches, text fields, radio choices and snackbars. Errors say
  what happened and how to recover. Deletion requires confirmation.
- The authored motion is continuous route playback. Camera transitions are brief;
  no bouncing status, looping pulse, automatic tour or gratuitous page entrances.
- The replay slider retains native adjustment actions and announces its purpose
  plus elapsed and total time, rather than an unexplained percentage.
- Offline-area management begins with a real map preview and the selected
  region's name, revision, source date and limitations. Installed regions are
  separated by quiet dividers, not a gallery of identical promotional cards.
  Import never silently switches the map; Use this map is a separate action.
- Map import/download progress and results return into view. Cancellation stays
  reachable. Destructive removal names the region and revision; the active and
  included regions remain protected. Download URL and checksum fields are
  progressively disclosed for the publisher workflow, not required onboarding.

## Do's and Don'ts

Do test font scaling, TalkBack labels, system Back, denied permissions, missing
sensors, offline startup, rotation, process recreation, failed exports and long
recordings. Do preserve attribution and distinguish downloaded map data from
live location. Do show synthetic provenance throughout replay and export.

Do not transplant the desktop report into a phone, claim lane accuracy from a
marker animation, require a model server to open the app, invent trips or sensor
health, obscure active recording, or report screenshot-only evidence as proof of
algorithm correctness.
