# IO-VNBD — Inertial and Odometry Vehicle Navigation Benchmark Dataset

Source: https://github.com/onyekpeu/IO-VNBD (paper: `README_1.pdf`, 15 pp.)
Authors: Uche Onyekpe, Vasile Palade, Stratis Kanarachos, Alicja Szkolnik (Coventry University).

## Purpose

Benchmark dataset for **ground-vehicle positioning from low-cost INS + odometry**, aimed at
deep-learning methods that bridge **GPS outages** (learn the mapping vehicle dynamics -> displacement).
Motivation: prior INS/GNSS deep-learning papers used private datasets, so results were not comparable.

## Scale

- ~100 h recorded driving (paper's conclusion states ~5,700 km over ~98 h), 8 drivers, public roads.
- **V- (vehicle CAN bus)**: ~40 h, ~1,300 km — England only.
- **S- (smartphone)**: ~58 h, ~4,400 km — England, France, Nigeria.
- > 20 min of stationary-vehicle data for sensor-bias estimation.
  >
- Varying tyre pressures (notations A–E, Table 5); driver E is "aggressive", all others "defensive".

## Hardware

- Racelogic VBOX Video HD2 CAN-bus logger + GPS antenna (roof-centre), **10 Hz** logging & GPS update.
- Smartphones via **AndroSensor** app, sampled every 100 ms but **GPS update only 1 Hz**:
  Huawei P20 Pro (most sets), Motorola Moto G7 Power (driver F, France), BlackBerry Priv (driver H).
- Vehicles: Ford Fiesta Titanium (FWD, the only CAN-bus/V- car), Volvo XC70, Renault Megane, Toyota Corolla Verso.
- Smartphone x-axis ~ direction of travel; alignment imperfect because of vehicle vibration, so
  **gravity X/Y/Z columns are provided to correct measured acceleration**.

## Repo layout (all CSVs are **Git LFS** pointers — must `git lfs pull` or use media.githubusercontent.com)

```
Synchronised V abd S datasets/        # V and S recorded simultaneously, manually time-aligned
  Categorised IOVNB Dataset/          # per driver-group: M(B), S(A), Vf(E), Vta(E), Vtb(E), Vw(E), Y(D)
     <group>/<run>/ -> V-x.csv, S-x.csv, V-x.JPG (route screenshot)
  Uncategorised IOVNB Dataset/
     V-Dataset/  (72 csv)   S-Dataset/  (72 csv)
Unsynchronised V and S Dataset/
  Categorised IOVNB (V) Dataset/
  Uncategorised IOVNB (V and S) Dataset/
     V-Dataset/  (90 csv)   S-Dataset/  (97 csv)
```

Naming: `V-` = vehicle CAN bus, `S-` = smartphone. Sets with no simultaneous counterpart live only
under "Unsynchronised". Typical file size ~11 MB (e.g. V-S1.csv = 10,967,129 B).
A txt file lists the sample indexes where GPS<->satellite communication was lost.

### Dataset groups

- `V-S1..S4` (driver A, Coventry/Rugby), `V-M` (B), `V-St1..St7` (C — no S- counterpart), `V-Y1,Y2` (D),
  driver E: `V-Vfa/Vfb*`, `V-Vta1a..Vta30`, `V-Vtb1..13`, `V-Vw1..Vw17`.
- Smartphone-only (Table A7): `S-T1..T11` France / Renault Megane / Moto G7 (1,026 min, 1,517 km),
  `S-I` Nigeria / Corolla Verso / P20 Pro (9.7 min, 0.06 km),
  `S-A1..A13` England / Volvo XC70 / BlackBerry Priv (638 min, 1,512 km).

## V- schema (29 cols, exact CSV header, comma+space separated)

No of GPS Satellites Available | Time Since Start of Day (s) | Latitude (deg) | Longitude (deg) |
Velocity (km/hr) | Heading (deg) | Height (km) | Vertical velocity (km/hr) | Sample period (s) |
Steering Angle (deg) | Wheel Speed Front Left / Front Right / Rear Left / Rear Right (rad/sec) |
Yaw Rate (deg/sec) | Indicated Vehicle Speed (km/hr) | Indicated Longitudinal Acceleration (g) |
Indicated Lateral Acceleration (g) | Handbrake (0/1) | Gear Requested (1-5) | Gear (1-5) |
Engine Speed (rev/min) | Coolant Temperature (degC) | Clutch Position (0/1) | Brake Pressure (psi) |
Brake Position (0/1) | Battery Voltage (V) | Air Temperature (degC) | Accelerator Pedal Position (%)

Sample row:
`11.0,32869.0,52.4017192,-1.5053331,19.969,241.713,110.19,0.2,0.1,31.0,20.39999,19.98,20.39,19.82999,-5.100006,20.2,0.0,-0.109139,0.0,3.0,3.0,1342.0,40.0,0.0,-0.2200012,0.0,14.3,15.0,8.5`

## S- schema (24 cols, exact CSV header)

GPS LATITUDE (deg) | GPS LONGITUDE (deg) | GPS ALTITUDE (m) | GPS SPEED (kmh) | GPS ACCURACY (m) |
GPS ORIENTATION (deg) | GPS SATELLITES IN RANGE (e.g. "27 / 28" — string, not numeric) |
TIME SINCE START (ms) | DATE (YYYY-MO-DD HH-MI-SS_SSS) | ACCELEROMETER X/Y/Z (m/s^2) |
GRAVITY X/Y/Z (m/s^2) | GYROSCOPE X/Y/Z (rad/s) | MAGNETIC FIELD X/Y/Z (uT) |
ORIENTATION (Azimuth) (deg) | ORIENTATION (Pitch) (deg) | ORIENTATION (Roll) (deg)

Sample row:
`52.40166,-1.50529,147.5,5.57,3,241.65,27 / 28,2922,2019-09-08 10:07:49:546,0.1002,1.5390,9.8338,0.0028,0.0048,9.8066,0.0187,-0.0607,-0.0069,-5.87,-26.37,30.31,18.78,-78.2,-153.5`

Header encoding gotcha: units are mojibake in the raw files (`m/s?`, `Â°`, `Î¼T`) — read with
`encoding='latin-1'` or normalise column names. Paper's Table 4 mislabels gyro cols (Pitch twice);
the CSV header is authoritative: GYROSCOPE X/Y/Z.
Driver F's S-T1..T9 lack 3-axis orientation and magnetic-field data.

## 32 scenarios covered (Table 2)

hard brake; sharp left/right turn; swift manoeuvres; round-about; rain; night & day; skid;
mountain/hills; dirt & gravel roads; country roads; motorway; town-centre; traffic congestion;
successive left-right turns; varying accelerations in short duration; A-roads; B-roads; wet roads;
U-turns / reverse; mud road; varying tyre pressure; drifts; bumps; inner-city; winding roads;
zig-zag; approximate straight-line motion; parking; potholes; residential roads; stationary; valley.

## Practical notes for use

- Sampling: V- is uniform 10 Hz (`Sample period` = 0.1 s). S- inertial is ~10 Hz but GPS ground truth
  is 1 Hz and repeats between fixes (see the identical lat/lon rows in the sample) — upsampling
  artefact to handle before using S- GPS as a label.
- Ground truth = GPS lat/lon; typical benchmark task is to simulate a GPS outage (e.g. 10-30 s / 90 s)
  and regress displacement from inertial + odometry inputs.
- Useful V- input features for displacement learning: 4x wheel speeds, yaw rate, steering angle,
  longitudinal/lateral acceleration, indicated speed.
- Wheel-speed -> distance needs the tyre rolling radius; tyre pressures vary per set (Table 5), and
  the "E" notation means pressure not recorded.
- The paper mentions "useful python development tools" in the repo; they are **not** present in the
  current repo tree (only data + README + README_1.pdf).
