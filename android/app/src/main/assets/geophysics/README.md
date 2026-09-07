# WMM2025 reference coefficients

These are geophysical reference data, not AI/ML weights.

- Provider: NOAA / British Geological Survey World Magnetic Model 2025.
- GeographicLib-format distribution: `https://downloads.sourceforge.net/project/geographiclib/magnetic-distrib/wmm2025.tar.bz2`
- Archive SHA-256: `89ae7a34e38c9d7ef741a60ec78922eac3a4daa1ec2862e4f95165c1e7fd0089`
- Packaged data are the unmodified `magnetic/wmm2025.wmm` and `magnetic/wmm2025.wmm.cof` members.
- Model interval used by SETU: 2025 inclusive to 2030 exclusive; out-of-range values are not extrapolated.
- Reference test source: `https://www.ncei.noaa.gov/sites/default/files/2024-12/WMM2025COF.zip`
- NOAA archive SHA-256: `2e76569370d081f2cd7919490218bd094ca9afde347b198eff5621e0af460d03`

The Android test asset `WMM2025_TestValues.txt` comes from that NOAA archive
(text line endings are normalized). GeographicLib 2.5 evaluates these coefficients;
its MIT/X11 license is packaged separately under `licenses/GeographicLib-MIT.txt`.
Its source archive and checksum are pinned in `core/CMakeLists.txt`.
