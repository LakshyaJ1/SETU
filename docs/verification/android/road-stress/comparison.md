# Synthetic road-stress comparison

**Not field validation or release approval.**

675 trials, 135 conditions, 5 paired seeds on CPH2467.
120 s GPS warmup; 200 Hz IMU; 10 Hz scoring; no blackout GPS or absolute attitude.
Missing outputs remain in the within-10-m denominator.

CV holds the last GPS velocity. IMU is unconstrained native propagation. Car adds the current vehicle constraints; it is not applicable to scooter lean.

| Algorithm | Profile | Outage s | Available % | Within 10 m % | Bootstrap 95% % | Missing ends | Benchmark |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| car | stationary | 10 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | smooth_cruise | 10 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | turns_and_stops | 10 | 100.0 | 74.5 | 52.3–95.6 | 0 | FAIL |
| car | rough_turns | 10 | 100.0 | 84.4 | 61.0–100.0 | 0 | FAIL |
| car | potholes_turns | 10 | 100.0 | 83.0 | 56.8–100.0 | 0 | FAIL |
| car | scooter_lean_potholes | 10 | 100.0 | 80.4 | 49.1–100.0 | 0 | FAIL |
| car | scooter_sensor_clipping | 10 | 50.5 | 47.3 | 41.0–50.5 | 5 | FAIL |
| car | rough_imu_gap | 10 | 41.6 | 37.6 | 29.7–41.6 | 5 | FAIL |
| car | phone_handling | 10 | 31.7 | 29.7 | 25.7–31.7 | 5 | FAIL |
| car | stationary | 30 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | smooth_cruise | 30 | 100.0 | 70.2 | 52.6–87.7 | 0 | FAIL |
| car | turns_and_stops | 30 | 100.0 | 54.7 | 29.9–77.7 | 0 | FAIL |
| car | rough_turns | 30 | 100.0 | 47.9 | 30.0–63.9 | 0 | FAIL |
| car | potholes_turns | 30 | 100.0 | 52.6 | 31.8–69.7 | 0 | FAIL |
| car | scooter_lean_potholes | 30 | 100.0 | 49.9 | 23.0–75.7 | 0 | FAIL |
| car | scooter_sensor_clipping | 30 | 16.9 | 15.9 | 13.8–16.9 | 5 | FAIL |
| car | rough_imu_gap | 30 | 14.0 | 12.6 | 10.0–14.0 | 5 | FAIL |
| car | phone_handling | 30 | 10.6 | 10.0 | 8.6–10.6 | 5 | FAIL |
| car | stationary | 60 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | smooth_cruise | 60 | 97.0 | 41.7 | 26.4–62.5 | 5 | FAIL |
| car | turns_and_stops | 60 | 100.0 | 45.5 | 21.6–67.8 | 0 | FAIL |
| car | rough_turns | 60 | 100.0 | 24.3 | 15.3–32.6 | 0 | FAIL |
| car | potholes_turns | 60 | 100.0 | 33.1 | 15.9–53.9 | 0 | FAIL |
| car | scooter_lean_potholes | 60 | 100.0 | 31.6 | 11.5–57.1 | 0 | FAIL |
| car | scooter_sensor_clipping | 60 | 8.5 | 8.0 | 6.9–8.5 | 5 | FAIL |
| car | rough_imu_gap | 60 | 7.0 | 6.3 | 5.0–7.0 | 5 | FAIL |
| car | phone_handling | 60 | 5.3 | 5.0 | 4.3–5.3 | 5 | FAIL |
| car | stationary | 120 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | smooth_cruise | 120 | 48.6 | 20.9 | 13.2–31.3 | 5 | FAIL |
| car | turns_and_stops | 120 | 100.0 | 22.7 | 10.8–33.9 | 0 | FAIL |
| car | rough_turns | 120 | 100.0 | 12.2 | 7.7–16.3 | 0 | FAIL |
| car | potholes_turns | 120 | 100.0 | 17.1 | 8.0–28.5 | 0 | FAIL |
| car | scooter_lean_potholes | 120 | 100.0 | 15.8 | 5.8–28.6 | 0 | FAIL |
| car | scooter_sensor_clipping | 120 | 4.2 | 4.0 | 3.4–4.2 | 5 | FAIL |
| car | rough_imu_gap | 120 | 3.5 | 3.2 | 2.5–3.5 | 5 | FAIL |
| car | phone_handling | 120 | 2.7 | 2.5 | 2.2–2.7 | 5 | FAIL |
| car | stationary | 180 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| car | smooth_cruise | 180 | 32.4 | 13.9 | 8.8–20.8 | 5 | FAIL |
| car | turns_and_stops | 180 | 100.0 | 15.2 | 7.2–22.6 | 0 | FAIL |
| car | rough_turns | 180 | 100.0 | 8.1 | 5.1–10.9 | 0 | FAIL |
| car | potholes_turns | 180 | 100.0 | 11.4 | 5.3–19.0 | 0 | FAIL |
| car | scooter_lean_potholes | 180 | 100.0 | 10.6 | 3.8–19.1 | 0 | FAIL |
| car | scooter_sensor_clipping | 180 | 2.8 | 2.7 | 2.3–2.8 | 5 | FAIL |
| car | rough_imu_gap | 180 | 2.3 | 2.1 | 1.7–2.3 | 5 | FAIL |
| car | phone_handling | 180 | 1.8 | 1.7 | 1.4–1.8 | 5 | FAIL |
| cv | stationary | 10 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| cv | smooth_cruise | 10 | 100.0 | 100.0 | 100.0–100.0 | 0 | pass |
| cv | turns_and_stops | 10 | 100.0 | 57.2 | 48.3–71.3 | 0 | FAIL |
| cv | rough_turns | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | potholes_turns | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | scooter_lean_potholes | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | scooter_sensor_clipping | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | rough_imu_gap | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | phone_handling | 10 | 100.0 | 39.4 | 17.0–66.5 | 0 | FAIL |
| cv | stationary | 30 | 100.0 | 100.0 | 100.0–100.0 | 0 | FAIL |
| cv | smooth_cruise | 30 | 100.0 | 78.7 | 59.1–98.0 | 0 | FAIL |
| cv | turns_and_stops | 30 | 100.0 | 19.2 | 16.2–23.9 | 0 | FAIL |
| cv | rough_turns | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | potholes_turns | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | scooter_lean_potholes | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | scooter_sensor_clipping | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | rough_imu_gap | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | phone_handling | 30 | 100.0 | 13.2 | 5.7–22.3 | 0 | FAIL |
| cv | stationary | 60 | 100.0 | 99.1 | 97.3–100.0 | 0 | FAIL |
| cv | smooth_cruise | 60 | 100.0 | 52.0 | 29.8–75.4 | 0 | FAIL |
| cv | turns_and_stops | 60 | 100.0 | 9.6 | 8.1–12.0 | 0 | FAIL |
| cv | rough_turns | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | potholes_turns | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | scooter_lean_potholes | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | scooter_sensor_clipping | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | rough_imu_gap | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | phone_handling | 60 | 100.0 | 6.6 | 2.9–11.2 | 0 | FAIL |
| cv | stationary | 120 | 100.0 | 80.7 | 59.8–100.0 | 0 | FAIL |
| cv | smooth_cruise | 120 | 100.0 | 26.0 | 14.9–37.7 | 0 | FAIL |
| cv | turns_and_stops | 120 | 100.0 | 4.8 | 4.1–6.0 | 0 | FAIL |
| cv | rough_turns | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | potholes_turns | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | scooter_lean_potholes | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | scooter_sensor_clipping | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | rough_imu_gap | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | phone_handling | 120 | 100.0 | 3.3 | 1.4–5.6 | 0 | FAIL |
| cv | stationary | 180 | 100.0 | 71.0 | 44.8–97.1 | 0 | FAIL |
| cv | smooth_cruise | 180 | 100.0 | 17.3 | 9.9–25.2 | 0 | FAIL |
| cv | turns_and_stops | 180 | 100.0 | 3.2 | 2.7–4.0 | 0 | FAIL |
| cv | rough_turns | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| cv | potholes_turns | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| cv | scooter_lean_potholes | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| cv | scooter_sensor_clipping | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| cv | rough_imu_gap | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| cv | phone_handling | 180 | 100.0 | 2.2 | 1.0–3.7 | 0 | FAIL |
| imu | stationary | 10 | 90.1 | 90.1 | 90.1–90.1 | 5 | FAIL |
| imu | smooth_cruise | 10 | 90.1 | 85.7 | 77.0–90.1 | 5 | FAIL |
| imu | turns_and_stops | 10 | 90.1 | 85.0 | 74.7–90.1 | 5 | FAIL |
| imu | rough_turns | 10 | 90.1 | 79.4 | 68.3–90.1 | 5 | FAIL |
| imu | potholes_turns | 10 | 90.1 | 79.4 | 68.3–90.1 | 5 | FAIL |
| imu | scooter_lean_potholes | 10 | 90.1 | 79.4 | 67.5–90.1 | 5 | FAIL |
| imu | scooter_sensor_clipping | 10 | 66.3 | 52.7 | 39.8–68.1 | 5 | FAIL |
| imu | rough_imu_gap | 10 | 41.6 | 41.6 | 41.6–41.6 | 5 | FAIL |
| imu | phone_handling | 10 | 90.1 | 79.2 | 67.3–90.1 | 5 | FAIL |
| imu | stationary | 30 | 30.2 | 30.2 | 30.2–30.2 | 5 | FAIL |
| imu | smooth_cruise | 30 | 30.2 | 28.8 | 25.8–30.2 | 5 | FAIL |
| imu | turns_and_stops | 30 | 30.2 | 28.5 | 25.0–30.2 | 5 | FAIL |
| imu | rough_turns | 30 | 30.2 | 26.6 | 22.9–30.2 | 5 | FAIL |
| imu | potholes_turns | 30 | 30.2 | 26.6 | 22.9–30.2 | 5 | FAIL |
| imu | scooter_lean_potholes | 30 | 30.2 | 26.6 | 22.7–30.2 | 5 | FAIL |
| imu | scooter_sensor_clipping | 30 | 22.3 | 17.7 | 13.4–22.9 | 5 | FAIL |
| imu | rough_imu_gap | 30 | 14.0 | 14.0 | 14.0–14.0 | 5 | FAIL |
| imu | phone_handling | 30 | 30.2 | 26.6 | 22.6–30.2 | 5 | FAIL |
| imu | stationary | 60 | 15.1 | 15.1 | 15.1–15.1 | 5 | FAIL |
| imu | smooth_cruise | 60 | 15.1 | 14.4 | 12.9–15.1 | 5 | FAIL |
| imu | turns_and_stops | 60 | 15.1 | 14.3 | 12.5–15.1 | 5 | FAIL |
| imu | rough_turns | 60 | 15.1 | 13.3 | 11.5–15.1 | 5 | FAIL |
| imu | potholes_turns | 60 | 15.1 | 13.3 | 11.5–15.1 | 5 | FAIL |
| imu | scooter_lean_potholes | 60 | 15.1 | 13.3 | 11.3–15.1 | 5 | FAIL |
| imu | scooter_sensor_clipping | 60 | 11.1 | 8.9 | 6.7–11.4 | 5 | FAIL |
| imu | rough_imu_gap | 60 | 7.0 | 7.0 | 7.0–7.0 | 5 | FAIL |
| imu | phone_handling | 60 | 15.1 | 13.3 | 11.3–15.1 | 5 | FAIL |
| imu | stationary | 120 | 7.6 | 7.6 | 7.6–7.6 | 5 | FAIL |
| imu | smooth_cruise | 120 | 7.6 | 7.2 | 6.5–7.6 | 5 | FAIL |
| imu | turns_and_stops | 120 | 7.6 | 7.1 | 6.3–7.6 | 5 | FAIL |
| imu | rough_turns | 120 | 7.6 | 6.7 | 5.7–7.6 | 5 | FAIL |
| imu | potholes_turns | 120 | 7.6 | 6.7 | 5.7–7.6 | 5 | FAIL |
| imu | scooter_lean_potholes | 120 | 7.6 | 6.7 | 5.7–7.6 | 5 | FAIL |
| imu | scooter_sensor_clipping | 120 | 5.6 | 4.4 | 3.3–5.7 | 5 | FAIL |
| imu | rough_imu_gap | 120 | 3.5 | 3.5 | 3.5–3.5 | 5 | FAIL |
| imu | phone_handling | 120 | 7.6 | 6.7 | 5.7–7.6 | 5 | FAIL |
| imu | stationary | 180 | 5.1 | 5.1 | 5.1–5.1 | 5 | FAIL |
| imu | smooth_cruise | 180 | 5.1 | 4.8 | 4.3–5.1 | 5 | FAIL |
| imu | turns_and_stops | 180 | 5.1 | 4.8 | 4.2–5.1 | 5 | FAIL |
| imu | rough_turns | 180 | 5.1 | 4.5 | 3.8–5.1 | 5 | FAIL |
| imu | potholes_turns | 180 | 5.1 | 4.5 | 3.8–5.1 | 5 | FAIL |
| imu | scooter_lean_potholes | 180 | 5.1 | 4.5 | 3.8–5.1 | 5 | FAIL |
| imu | scooter_sensor_clipping | 180 | 3.7 | 3.0 | 2.2–3.8 | 5 | FAIL |
| imu | rough_imu_gap | 180 | 2.3 | 2.3 | 2.3–2.3 | 5 | FAIL |
| imu | phone_handling | 180 | 5.1 | 4.4 | 3.8–5.1 | 5 | FAIL |

Exploratory percentile bootstrap: 2000 resamples of complete seeds, paired across algorithms. Few synthetic seeds do not establish field confidence.

## Boundaries

- Synthetic stress physics, not measured Indian-road hazard prevalence.
- No Android heading initialization, learned model, map matching or GPS recovery test.
- Car constraints on leaning profiles are a negative control, not scooter support.
- Missing predictions count as failures; unavailable endpoints are null, not zero.
- Benchmark success is not approval against every project release gate.

Executable SHA-256: `0ad32cd7954b59b135dc24a106e4d567caea179e83fabb89edb63debd1d142d4`.
Experiment manifest SHA-256: `3f032641828e72f55c36c4d0c3085e6064f70b112724a93fb093216e144e8298`.
