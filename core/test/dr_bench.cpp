// GNSS-denied dead-reckoning benchmark for the SETU engine.
//
// Runs the shipping engine against synthetic drives with known ground truth, cuts GNSS partway
// through, and measures what the requirements actually ask for:
//
//   REQ-P1  horizontal drift < 10 % of distance travelled during the blackout
//   REQ-P2  < 5 m final error over a 50 m creep in under a minute
//   REQ-P3  < 100 m final error over 1 km at 60 km/h
//
// The phone is given a random, unknown mount rotation in every run, so the engine has to work out
// the vehicle axes for itself; nothing here tells it how the phone is sitting. IMU samples carry
// MEMS-grade white noise, a turn-on bias and a bias random walk.
//
// Build for the device (see core/test/README.md) and run it there: it exercises the same
// arm64-v8a code path the app ships.

#include "setu_engine.h"

#include <GeographicLib/LocalCartesian.hpp>
#include <Eigen/Geometry>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <numbers>
#include <random>
#include <vector>

using Vector3 = Eigen::Vector3d;
using Matrix3 = Eigen::Matrix3d;
using RowMatrix3 = Eigen::Matrix<double, 3, 3, Eigen::RowMajor>;

namespace {
constexpr double g0 = 9.80665;
constexpr double pi = std::numbers::pi;
constexpr double origin_latitude = 28.6139;    // Delhi, inside the bundled region
constexpr double origin_longitude = 77.2090;

struct Segment {
    double seconds;
    double target_speed;   // m/s
    double yaw_rate;       // rad/s
};

struct Profile {
    const char* name;
    const char* requirement;
    double blackout_after;          // seconds of GNSS before the cut
    double limit_metres;            // absolute final-error limit, or 0 to use the ratio only
    double ratio_limit;             // drift / distance, or 0 to skip
    std::vector<Segment> segments;
};

struct Result {
    double distance = 0;
    double final_error = 0;
    double peak_error = 0;
    double reported_radius = 0;
    double blackout_seconds = 0;
    double along_track = 0, cross_track = 0, speed_error = 0;
    int zupts = 0, nhcs = 0, cts = 0, svo = 0;
    double mount_weight = 0, svo_scale = 0, mount_error_degrees = 0;
    bool held = false;              // engine still produced a position at the end
};

// Random but plausible phone mount: any yaw, modest pitch and roll.
Matrix3 random_mount(std::mt19937_64& generator) {
    std::uniform_real_distribution<double> yaw(-pi, pi), tilt(-0.45, 0.45);
    return (Eigen::AngleAxisd(yaw(generator), Vector3::UnitZ()) *
            Eigen::AngleAxisd(tilt(generator), Vector3::UnitY()) *
            Eigen::AngleAxisd(tilt(generator), Vector3::UnitX())).toRotationMatrix();
}

Result run(const Profile& profile, uint64_t seed, const char* geophysics, bool constraints) {
    Result result;
    std::mt19937_64 generator(seed);
    std::normal_distribution<double> unit(0.0, 1.0);

    SetuEngine* engine = setu_engine_create(geophysics);
    if (!engine) { std::printf("  engine_create failed (geophysics path %s)\n", geophysics); return result; }

    setu_engine_constraints(engine, constraints ? 1 : 0);
    GeographicLib::LocalCartesian frame(origin_latitude, origin_longitude, 0);

    const double rate = 200.0, dt = 1.0 / rate;
    const Matrix3 mount = random_mount(generator);      // phone <- vehicle

    // MEMS error model: turn-on bias plus a slow random walk, both unknown to the engine.
    Vector3 accel_bias(unit(generator) * 0.08, unit(generator) * 0.08, unit(generator) * 0.08);
    Vector3 gyro_bias(unit(generator) * 0.004, unit(generator) * 0.004, unit(generator) * 0.004);

    Vector3 position = Vector3::Zero();       // ENU, metres
    Vector3 velocity = Vector3::Zero();
    double heading = 0;                        // radians, 0 = +North
    double speed = 0;

    int64_t t = 1000000000LL;                  // start away from zero; engine rejects t <= 0
    double elapsed = 0, blackout_elapsed = 0;
    int64_t last_fix_ns = 0;
    bool blackout = false;
    double axle_phase = 0, engine_phase = 0;
    Vector3 blackout_start_position = Vector3::Zero();
    double estimate[SETU_ESTIMATE_SIZE] = {0};

    for (const Segment& segment : profile.segments) {
        const int steps = static_cast<int>(segment.seconds * rate);
        for (int step = 0; step < steps; ++step) {
            // --- truth propagation ------------------------------------------------------------
            const double previous_speed = speed;
            const double command = std::clamp(segment.target_speed - speed, -3.5 * dt, 2.5 * dt);
            speed = std::max(0.0, speed + command);
            // Tyres cap lateral acceleration; a stopped vehicle cannot yaw.
            double yaw_rate = segment.yaw_rate;
            if (speed > 0.1) {
                const double bound = 0.45 * g0 / std::max(speed, 0.1);
                yaw_rate = std::clamp(yaw_rate, -bound, bound);
            } else {
                yaw_rate = 0;
            }
            heading += yaw_rate * dt;

            const Vector3 forward(std::sin(heading), std::cos(heading), 0);
            // right = forward x up, which keeps the vehicle triad right-handed. Using "left" here
            // gave a determinant of -1 and the engine rightly refused the attitude.
            const Vector3 right(std::cos(heading), -std::sin(heading), 0);
            const Vector3 next_velocity = forward * speed;
            const Vector3 world_acceleration = (next_velocity - velocity) / dt;
            velocity = next_velocity;
            position += velocity * dt;
            if (blackout) blackout_elapsed += dt;
            (void)previous_speed;

            // Vehicle attitude: x = right, y = forward, z = up, matching the ENU convention the
            // engine reports bearings in (atan2(vx, vy)).
            Matrix3 vehicle;
            vehicle.col(0) = right;
            vehicle.col(1) = forward;
            vehicle.col(2) = Vector3::UnitZ();

            // --- synthesise the phone IMU ------------------------------------------------------
            Vector3 specific_force = vehicle.transpose() * (world_acceleration + Vector3(0, 0, g0));
            const Vector3 body_rate = vehicle.transpose() * Vector3(0, 0, yaw_rate);
            // Road and engine vibration. This is not decoration: a smooth constant-velocity cruise
            // with no vibration is, to an accelerometer, exactly a vehicle standing still, so a
            // simulator without it cannot exercise the stop detector honestly. Amplitude grows with
            // speed; the axle line sits at v / (2*pi*R).
            const double axle_hz = speed / (2 * pi * 0.31);
            axle_phase += 2 * pi * axle_hz * dt;
            engine_phase += 2 * pi * (speed > 0.3 ? 28.0 : 11.0) * dt;
            const double road = 0.18 + 0.085 * speed;
            for (int axis = 0; axis < 3; ++axis) {
                specific_force(axis) += road * (0.6 * std::sin(axle_phase + axis) +
                                                0.3 * std::sin(2 * axle_phase + axis) +
                                                0.2 * std::sin(engine_phase + axis)) +
                                        road * 0.35 * unit(generator);
            }
            accel_bias += Vector3(unit(generator), unit(generator), unit(generator)) * 1.6e-3 * std::sqrt(dt);
            gyro_bias += Vector3(unit(generator), unit(generator), unit(generator)) * 5e-5 * std::sqrt(dt);
            const Vector3 phone_accel = mount * specific_force + accel_bias +
                Vector3(unit(generator), unit(generator), unit(generator)) * 0.05;
            const Vector3 phone_gyro = mount * body_rate + gyro_bias +
                Vector3(unit(generator), unit(generator), unit(generator)) * 0.004;

            // --- feed the engine ---------------------------------------------------------------
            // Attitude comes from the fused rotation vector in the real app; here it is the true
            // phone attitude with realistic noise, refreshed at 10 Hz.
            if (step % 20 == 0) {
                const Matrix3 phone_attitude = vehicle * mount.transpose();
                const Matrix3 noisy = phone_attitude *
                    Eigen::AngleAxisd(unit(generator) * 0.02, Vector3::UnitZ()).toRotationMatrix();
                const RowMatrix3 row = noisy;
                setu_engine_attitude(engine, t, row.data(), 0.08);
            }
            setu_engine_imu(engine, t, phone_accel.data(), phone_gyro.data());

            if (!blackout && elapsed >= profile.blackout_after) {
                blackout = true;
                blackout_start_position = position;
            }
            if (!blackout && t - last_fix_ns >= 1000000000LL) {
                last_fix_ns = t;
                double latitude, longitude, altitude;
                frame.Reverse(position.x(), position.y(), position.z(), latitude, longitude, altitude);
                const double course = std::fmod(heading / pi * 180 + 360, 360);
                const double values[10] = {latitude, longitude, altitude, 4.0, 6.0,
                                           speed, course, 0.3, 5.0, 0.0};
                setu_engine_gnss(engine, t, values);
            }

            // --- score --------------------------------------------------------------------------
            if (blackout && step % 20 == 0) {
                if (setu_engine_poll(engine, estimate) == 1 && std::isfinite(estimate[2])) {
                    double east, north, up;
                    frame.Forward(estimate[2], estimate[3], std::isfinite(estimate[4]) ? estimate[4] : 0,
                                  east, north, up);
                    const double error = std::hypot(east - position.x(), north - position.y());
                    result.final_error = error;
                    result.peak_error = std::max(result.peak_error, error);
                    result.reported_radius = estimate[7];
                    result.held = true;
                    // Split the error into along-track and cross-track relative to the true
                    // heading: NHC and ZUPT bound the cross-track term, so if the total is
                    // dominated by along-track the missing ingredient is a speed observation.
                    const Vector3 offset(east - position.x(), north - position.y(), 0);
                    result.along_track = std::abs(offset.dot(forward));
                    result.cross_track = std::abs(offset.dot(right));
                    result.speed_error = estimate[5] - speed;
                } else {
                    result.held = false;
                }
                result.zupts = static_cast<int>(estimate[20]);
                result.nhcs = static_cast<int>(estimate[21]);
                result.cts = static_cast<int>(estimate[22]);
                result.mount_weight = estimate[23];
                result.svo = static_cast<int>(estimate[24]);
                result.svo_scale = estimate[25];
                // The truth is known here: the vehicle forward axis is e_y, so in phone
                // coordinates it is mount * e_y. Comparing tells us whether the estimated axes are
                // the source of the heading error or merely carrying it.
                const Vector3 true_forward = mount * Vector3::UnitY();
                const Vector3 got(estimate[26], estimate[27], estimate[28]);
                if (got.norm() > 0.5) {
                    result.mount_error_degrees =
                        std::acos(std::clamp(true_forward.normalized().dot(got.normalized()), -1.0, 1.0)) * 180 / pi;
                }
            }
            if (getenv("SETU_TRACE") && step % 400 == 0) {
                double probe[SETU_ESTIMATE_SIZE];
                setu_engine_poll(engine, probe);
                double truth_latitude, truth_longitude, truth_altitude;
                frame.Reverse(position.x(), position.y(), position.z(),
                              truth_latitude, truth_longitude, truth_altitude);
                std::printf("    t=%6.1fs status=%.0f acc=%.0f gated=%.0f lat=%.6f trueLat=%.6f v=%.1f trueV=%.1f nhc=%.0f cts=%.0f\n",
                            elapsed, probe[0], probe[10], probe[11], probe[2], truth_latitude,
                            probe[5], speed, probe[21], probe[22]);
            }
            t += static_cast<int64_t>(dt * 1e9);
            elapsed += dt;
        }
    }
    result.distance = (position - blackout_start_position).norm();
    result.blackout_seconds = blackout_elapsed;
    setu_engine_destroy(engine);
    return result;
}

double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) return 0;
    std::sort(values.begin(), values.end());
    size_t index = static_cast<size_t>(fraction * (values.size() - 1) + 0.5);
    return values[std::min(index, values.size() - 1)];
}
}  // namespace

int main(int argc, char** argv) {
    const char* geophysics = argc > 1 ? argv[1] : "/data/local/tmp/setu-geophysics";
    const int repeats = argc > 2 ? std::atoi(argv[2]) : 12;

    // Straight cruise punctuated by gentle curves. The curves are what make speed observable
    // without GNSS, through the coordinated-turn relation.
    std::vector<Segment> tunnel{{40, 16.7, 0.0}};
    for (int i = 0; i < 6; ++i) {
        tunnel.push_back({8, 16.7, 0.0});
        tunnel.push_back({4, 16.7, i % 2 ? 0.07 : -0.07});
    }
    tunnel.push_back({10, 16.7, 0.0});

    std::vector<Segment> creep{{30, 4.0, 0.0}, {6, 0.0, 0.0}};
    for (int i = 0; i < 5; ++i) {
        creep.push_back({4, 3.0, 0.0});
        creep.push_back({3, 2.5, i % 2 ? 0.35 : -0.35});
        creep.push_back({3, 0.0, 0.0});
    }

    // The stop segments were 3 s, which is not a stop: braking from 8 m/s at 3.5 m/s^2 takes 2.3 s,
    // so the vehicle stood still for about half a second and the profile never exercised a real
    // halt - every urban run reported zero zero-velocity updates. A signal-controlled junction
    // holds traffic for tens of seconds; 12 s is still conservative.
    std::vector<Segment> urban{{40, 12.0, 0.0}};
    for (int i = 0; i < 6; ++i) {
        urban.push_back({10, 13.0, 0.0});
        urban.push_back({4, 8.0, i % 2 ? 0.25 : -0.25});
        urban.push_back({12, 0.0, 0.0});
    }

    const std::vector<Profile> profiles{
        {"REQ-P3  tunnel, ~1 km at 60 km/h", "p90 final error < 100 m", 40, 100, 0.10, tunnel},
        {"REQ-P2  parking creep, ~50 m",     "p90 final error < 5 m",   30,   5, 0.0,  creep},
        {"REQ-P1  urban blackout",           "p90 drift < 10 % of distance", 40, 0, 0.10, urban},
    };

    const bool constraints = !getenv("SETU_NO_DR");
    std::printf("dead-reckoning constraints: %s\n", constraints ? "ON" : "OFF (GNSS-only baseline)");

    int failures = 0;
    for (const Profile& profile : profiles) {
        std::printf("\n%s\n  target: %s\n", profile.name, profile.requirement);
        std::vector<double> errors, ratios;
        Result last;
        int withheld = 0;
        for (int index = 0; index < repeats; ++index) {
            last = run(profile, 0xBEEFu + index * 7919u, geophysics, constraints);
            if (!last.held) {
                ++withheld;
                errors.push_back(1e9);
                ratios.push_back(1e9);
                continue;
            }
            errors.push_back(last.final_error);
            ratios.push_back(last.distance > 1 ? last.final_error / last.distance : 0);
        }
        const double p90_error = percentile(errors, 0.9);
        const double p90_ratio = percentile(ratios, 0.9);
        std::printf("  last run: mount error %.1f deg, along-track %.0f m, cross-track %.0f m, speed error %+.1f m/s\n",

                    last.mount_error_degrees, last.along_track, last.cross_track, last.speed_error);
        std::printf("  blackout %.0f s over %.0f m   constraints: %d ZUPT, %d NHC, %d CTS, %d SVO (scale %.2f m/Hz), mount %.1f\n",
                    last.blackout_seconds, last.distance, last.zupts, last.nhcs, last.cts,
                    last.svo, last.svo_scale, last.mount_weight);
        std::printf("  median final error %.1f m   p90 %.1f m   p90 drift %.1f %%   reported 95%% radius %.0f m   withheld %d/%d\n",
                    percentile(errors, 0.5), p90_error, p90_ratio * 100, last.reported_radius, withheld, repeats);
        bool pass = withheld == 0;
        if (profile.limit_metres > 0 && p90_error > profile.limit_metres) pass = false;
        if (profile.ratio_limit > 0 && p90_ratio > profile.ratio_limit) pass = false;
        std::printf("  %s\n", pass ? "PASS" : "FAIL");
        if (!pass) ++failures;
    }
    std::printf("\n%d of %zu profiles failed\n", failures, profiles.size());
    return failures == 0 ? 0 : 1;
}
