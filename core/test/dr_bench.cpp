#include "setu_engine.h"

#include <GeographicLib/LocalCartesian.hpp>
#include <Eigen/Geometry>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <numbers>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

using Vector3 = Eigen::Vector3d;
using Matrix3 = Eigen::Matrix3d;
using RowMatrix3 = Eigen::Matrix<double, 3, 3, Eigen::RowMajor>;

namespace {
constexpr double gravity = 9.80665;
constexpr double pi = std::numbers::pi;
constexpr double interval = 0.005;
constexpr int rate = 200;
constexpr int warmup_seconds = 120;
constexpr double acceleration_range = 156.9064;
constexpr double gyro_range = 34.90656;
constexpr double missing = std::numeric_limits<double>::quiet_NaN();

struct Profile {
    const char* name;
    bool stopped = false;
    bool turns = false;
    bool rough = false;
    bool potholes = false;
    bool lean = false;
    bool clipping = false;
    bool gap = false;
    bool handling = false;
};

const std::array<Profile, 9> profiles{{
    {"stationary", true},
    {"smooth_cruise"},
    {"turns_and_stops", false, true},
    {"rough_turns", false, true, true},
    {"potholes_turns", false, true, true, true},
    {"scooter_lean_potholes", false, true, true, true, true},
    {"scooter_sensor_clipping", false, true, true, true, true, true},
    {"rough_imu_gap", false, true, true, true, true, false, true},
    {"phone_handling", false, true, true, true, true, false, false, true},
}};

Matrix3 attitude(double heading, double roll) {
    return (Eigen::AngleAxisd(-heading, Vector3::UnitZ()) *
            Eigen::AngleAxisd(roll, Vector3::UnitY())).toRotationMatrix();
}

Vector3 angular_velocity(const Matrix3& previous, const Matrix3& current) {
    const Eigen::AngleAxisd change(previous.transpose() * current);
    return change.axis() * (change.angle() / interval);
}

double smooth_step(double fraction) {
    const double bounded = std::clamp(fraction, 0.0, 1.0);
    return bounded * bounded * (3.0 - 2.0 * bounded);
}

double pothole_height(double elapsed, bool severe) {
    const double phase = std::fmod(elapsed + 1.0, 7.0);
    const double duration = severe ? 0.08 : 0.25;
    if (phase >= duration) return 0.0;
    return -(severe ? 0.08 : 0.035) * std::pow(std::sin(pi * phase / duration), 4);
}

std::array<double, 2> command(double elapsed, const Profile& profile) {
    if (elapsed < 15) return {0, 0};
    if (elapsed < 105) {
        const double phase = std::fmod(elapsed - 15, 30.0);
        return {phase < 20 ? 10.0 : 3.0, phase < 10 ? 0.0 : (phase < 20 ? 0.15 : -0.2)};
    }
    if (profile.stopped) return {0, 0};
    if (elapsed < warmup_seconds || !profile.turns) return {12, 0};
    const double phase = std::fmod(elapsed - warmup_seconds, 60.0);
    if (phase < 12) return {10, 0};
    if (phase < 20) return {6, 0.25};
    if (phase < 30) return {0, 0};
    if (phase < 45) return {8, -0.15};
    return {12, 0};
}

double percentile(std::vector<double> values, double fraction) {
    if (values.empty()) return missing;
    std::sort(values.begin(), values.end());
    const auto index = static_cast<size_t>(std::ceil(fraction * values.size()));
    return values[std::clamp<size_t>(index, 1, values.size()) - 1];
}

std::string number(double value) {
    if (!std::isfinite(value)) return "null";
    char output[64];
    std::snprintf(output, sizeof(output), "%.10g", value);
    return output;
}

struct Score {
    int outputs = 0;
    int available = 0;
    int within_five = 0;
    int within_ten = 0;
    int covered = 0;
    int radii = 0;
    double final_error = missing;
    double final_along = missing;
    double final_cross = missing;
    double distance = 0;
    double peak_acceleration = 0;
    double peak_rotation = 0;
    int clipped_samples = 0;
    int dropped_samples = 0;
    std::vector<double> errors;
    std::vector<double> speed_errors;

    void observe(double error, double radius = missing) {
        outputs++;
        final_error = error;
        if (!std::isfinite(error)) return;
        available++;
        within_five += error <= 5;
        within_ten += error <= 10;
        errors.push_back(error);
        if (std::isfinite(radius)) { radii++; covered += error <= radius; }
    }

    double success_rate() const { return outputs ? static_cast<double>(within_ten) / outputs : 0; }
    bool meets_point_target() const { return outputs > 0 && success_rate() >= 0.9 && std::isfinite(final_error); }
};

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void self_test() {
    const Matrix3 previous = attitude(0, 0);
    const Matrix3 current = attitude(0.2 * interval, 0);
    require(std::abs(angular_velocity(previous, current).z() + 0.2) < 1e-10,
            "Clockwise navigation heading must give negative ENU gyro Z");
    require(std::abs(attitude(0.7, 0.4).determinant() - 1) < 1e-12, "Attitude must be a proper rotation");
    const Matrix3 mount = Eigen::AngleAxisd(0.6, Vector3::UnitX()).toRotationMatrix();
    require((angular_velocity(previous * mount.transpose(), current * mount.transpose()) -
            mount * Vector3(0, 0, -0.2)).norm() < 1e-9, "Mount transform must preserve body angular velocity");
    require(pothole_height(6, false) == 0 && std::abs(pothole_height(6.25, false)) < 1e-12,
            "Pothole must join the road continuously");
    require(std::abs(pothole_height(6.125, false) + 0.035) < 1e-12, "Pothole depth must match the fixture");
    Score score;
    for (int index = 0; index < 9; index++) score.observe(1);
    score.observe(missing);
    require(std::abs(score.success_rate() - 0.9) < 1e-12, "Missing predictions belong in the denominator");
    require(!score.meets_point_target(), "An unavailable endpoint must not masquerade as a final error");
    require(std::isnan(percentile({}, 0.9)), "Missing errors must not produce zero error");
    require(percentile({1, 2, 3, 4, 5}, 0.9) == 5, "Use documented nearest-rank quantiles");
    double travelled = 0;
    Vector3 position = Vector3::Zero();
    for (int index = 0; index < 2000; index++) {
        const Vector3 delta(std::sin(index * 2 * pi / 2000), std::cos(index * 2 * pi / 2000), 0);
        position += delta;
        travelled += delta.head<2>().norm();
    }
    require(travelled > 1999 && position.norm() < 1e-8, "Travelled distance is not endpoint displacement");
    std::puts("{\"type\":\"self_test\",\"passed\":true,\"checks\":10}");
}

Score run(const Profile& profile, int duration, uint64_t seed, const char* directory, const std::string& algorithm) {
    SetuEngine* engine = algorithm == "cv" ? nullptr : setu_engine_create(directory);
    require(algorithm == "cv" || engine != nullptr, "Could not create native engine");
    if (engine) setu_engine_constraints(engine, algorithm == "car" ? 1 : 0);
    GeographicLib::LocalCartesian frame(28.6139, 77.2090, 0);
    std::mt19937_64 generator(seed);
    std::normal_distribution<double> normal(0, 1);
    std::uniform_real_distribution<double> mount_yaw(-pi, pi), mount_tilt(-0.45, 0.45);
    const Matrix3 mount = (Eigen::AngleAxisd(mount_yaw(generator), Vector3::UnitZ()) *
        Eigen::AngleAxisd(mount_tilt(generator), Vector3::UnitY()) *
        Eigen::AngleAxisd(mount_tilt(generator), Vector3::UnitX())).toRotationMatrix();
    Vector3 acceleration_bias(normal(generator) * 0.08, normal(generator) * 0.08, normal(generator) * 0.08);
    Vector3 gyro_bias(normal(generator) * 0.004, normal(generator) * 0.004, normal(generator) * 0.004);
    Vector3 chassis = Vector3::Zero(), position = Vector3::Zero(), velocity = Vector3::Zero();
    Vector3 previous_position = Vector3::Zero(), previous_velocity = Vector3::Zero();
    Matrix3 previous_rotation = mount.transpose();
    Vector3 reference_position = Vector3::Zero(), reference_velocity = Vector3::Zero();
    int64_t reference_ns = 0;
    double heading = 0, speed = 0, yaw_rate = 0, lean_angle = 0;
    Score score;
    const bool trace = std::getenv("SETU_TRACE") != nullptr;

    for (int step = 0; step <= (warmup_seconds + duration) * rate; step++) {
        const double elapsed = step * interval;
        const bool blackout = step >= warmup_seconds * rate;
        const auto desired = command(elapsed, profile);
        speed = std::max(0.0, speed + std::clamp(desired[0] - speed, -3.5 * interval, 2.5 * interval));
        const double target_yaw = speed < 0.1 ? 0 : std::clamp(desired[1], -0.45 * gravity / speed, 0.45 * gravity / speed);
        yaw_rate += std::clamp(target_yaw - yaw_rate, -0.8 * interval, 0.8 * interval);
        if (step > 0) heading += yaw_rate * interval;
        const Vector3 forward(std::sin(heading), std::cos(heading), 0);
        const Vector3 right(std::cos(heading), -std::sin(heading), 0);
        if (step > 0) chassis += forward * (speed * interval);
        const double road_height = profile.potholes ? pothole_height(elapsed, profile.clipping) * smooth_step(speed / 2) : 0;
        const double target_lean = profile.lean ? std::atan2(speed * yaw_rate, gravity) : 0;
        lean_angle += std::clamp(target_lean - lean_angle, -1.2 * interval, 1.2 * interval);
        const Matrix3 vehicle = attitude(heading, lean_angle + road_height * 2);
        const double handling = profile.handling ? 1.7 * smooth_step((elapsed - warmup_seconds - 3) / 0.4) : 0;
        const Matrix3 active_mount = Eigen::AngleAxisd(handling, Vector3::UnitZ()).toRotationMatrix() * mount;
        const Matrix3 rotation = vehicle * active_mount.transpose();
        position = chassis + Vector3(0, 0, road_height);
        velocity = step == 0 ? Vector3::Zero().eval() : ((position - previous_position) / interval).eval();
        const Vector3 acceleration = step == 0 ? Vector3::Zero().eval() : ((velocity - previous_velocity) / interval).eval();
        if (step > warmup_seconds * rate) score.distance += (position - previous_position).head<2>().norm();

        acceleration_bias += Vector3(normal(generator), normal(generator), normal(generator)) * (1.6e-3 * std::sqrt(interval));
        gyro_bias += Vector3(normal(generator), normal(generator), normal(generator)) * (5e-5 * std::sqrt(interval));
        Vector3 measured_acceleration = rotation.transpose() * (acceleration + Vector3(0, 0, gravity)) + acceleration_bias;
        Vector3 measured_gyro = (step == 0 ? Vector3::Zero().eval() : angular_velocity(previous_rotation, rotation)) + gyro_bias;
        for (int axis = 0; axis < 3; axis++) {
            const double structural_noise = profile.rough && speed > 0.1 ?
                0.45 * normal(generator) + 0.6 * std::sin(2 * pi * 23 * elapsed + axis) : 0;
            measured_acceleration[axis] += structural_noise + normal(generator) * 0.05;
            measured_gyro[axis] += normal(generator) * 0.004;
        }
        score.peak_acceleration = std::max(score.peak_acceleration, measured_acceleration.norm());
        score.peak_rotation = std::max(score.peak_rotation, measured_gyro.norm());
        bool clipped = false;
        for (int axis = 0; axis < 3; axis++) {
            clipped |= std::abs(measured_acceleration[axis]) > acceleration_range || std::abs(measured_gyro[axis]) > gyro_range;
            measured_acceleration[axis] = std::clamp(measured_acceleration[axis], -acceleration_range, acceleration_range);
            measured_gyro[axis] = std::clamp(measured_gyro[axis], -gyro_range, gyro_range);
        }
        score.clipped_samples += clipped;
        const int64_t timestamp = 1000000000LL + static_cast<int64_t>(step) * 5000000LL;
        if (!blackout && step % 20 == 0) {
            const RowMatrix3 noisy = rotation * Eigen::AngleAxisd(normal(generator) * 0.02, Vector3::UnitZ()).toRotationMatrix();
            if (engine) setu_engine_attitude(engine, timestamp, noisy.data(), 0.08);
        }
        const bool dropped = profile.gap && step >= (warmup_seconds + 4) * rate && step < (warmup_seconds + 4) * rate + 40;
        score.dropped_samples += dropped;
        if (engine && !dropped) setu_engine_imu(engine, timestamp, measured_acceleration.data(), measured_gyro.data());
        if (!blackout && step % rate == 0) {
            reference_position = position + Vector3(normal(generator) * 3, normal(generator) * 3, normal(generator) * 4);
            const double observed_speed = std::max(0.0, speed + normal(generator) * 0.2);
            const double observed_heading = heading + normal(generator) * 0.04;
            reference_velocity = Vector3(std::sin(observed_heading), std::cos(observed_heading), 0) * observed_speed;
            reference_ns = timestamp;
            double latitude, longitude, altitude;
            frame.Reverse(reference_position.x(), reference_position.y(), reference_position.z(), latitude, longitude, altitude);
            const double observation[10] = {latitude, longitude, altitude, 4, 6, observed_speed,
                std::fmod(observed_heading * 180 / pi + 720, 360.0), 0.3, 5, 0};
            if (engine) setu_engine_gnss(engine, timestamp, observation);
        }

        if (blackout && step % 20 == 0) {
            double error = missing, radius = missing, predicted_speed = missing;
            Vector3 estimate_position = Vector3::Zero();
            bool available = false;
            if (algorithm == "cv" && reference_ns > 0) {
                estimate_position = reference_position + reference_velocity * ((timestamp - reference_ns) / 1e9);
                predicted_speed = reference_velocity.head<2>().norm();
                available = true;
            } else if (engine) {
                double estimate[SETU_ESTIMATE_SIZE];
                available = setu_engine_poll(engine, estimate) == 1 && std::isfinite(estimate[2]) &&
                    timestamp / 1e9 - estimate[1] <= 0.3;
                if (available) {
                    frame.Forward(estimate[2], estimate[3], std::isfinite(estimate[4]) ? estimate[4] : 0,
                                  estimate_position.x(), estimate_position.y(), estimate_position.z());
                    radius = estimate[7];
                    predicted_speed = estimate[5];
                }
            }
            if (available) {
                const Vector3 offset = estimate_position - position;
                error = offset.head<2>().norm();
                score.final_along = offset.dot(forward);
                score.final_cross = offset.dot(right);
                score.speed_errors.push_back(std::abs(predicted_speed - speed));
            } else { score.final_along = missing; score.final_cross = missing; }
            score.observe(error, radius);
            if (trace) std::printf("{\"type\":\"sample\",\"profile\":\"%s\",\"algorithm\":\"%s\",\"seed\":%llu,\"durationSeconds\":%d,\"outageSeconds\":%.1f,\"errorMeters\":%s,\"radius95Meters\":%s}\n",
                profile.name, algorithm.c_str(), static_cast<unsigned long long>(seed), duration,
                elapsed - warmup_seconds, number(error).c_str(), number(radius).c_str());
        }
        previous_position = position;
        previous_velocity = velocity;
        previous_rotation = rotation;
    }
    if (engine) setu_engine_destroy(engine);
    return score;
}
}

int main(int argc, char** argv) {
    try {
        if (argc > 1 && std::string(argv[1]) == "--self-test") { self_test(); return 0; }
        const char* directory = argc > 1 ? argv[1] : "/data/local/tmp/setu-geophysics";
        const int repeats = argc > 2 ? std::stoi(argv[2]) : 5;
        const std::string algorithm = argc > 3 ? argv[3] : (std::getenv("SETU_NO_DR") ? "imu" : "car");
        const int requested_duration = argc > 4 ? std::stoi(argv[4]) : 0;
        const int requested_profile = argc > 5 ? std::stoi(argv[5]) : -1;
        const std::array<int, 5> durations{10, 30, 60, 120, 180};
        require(repeats >= 1 && repeats <= 20, "Repeats must be in 1..20");
        require(algorithm == "cv" || algorithm == "imu" || algorithm == "car", "Algorithm must be cv, imu or car");
        require(requested_duration == 0 || std::find(durations.begin(), durations.end(), requested_duration) != durations.end(), "Duration must be 0, 10, 30, 60, 120 or 180");
        require(requested_profile >= -1 && requested_profile < static_cast<int>(profiles.size()), "Unknown profile index");
        std::puts("{\"type\":\"protocol\",\"schema\":\"setu.road-stress.v1\",\"synthetic\":true,\"warmupSeconds\":120,\"sensorHz\":200,\"scoreHz\":10,\"targetMeters\":10,\"jointTarget\":0.9,\"missingCountsAsFailure\":true,\"reference\":\"synthetic phone trajectory, not Indian-road field truth\",\"absoluteAttitudeDuringBlackout\":false,\"speedLockedAxleLine\":false}");
        int failed_cases = 0;
        for (size_t profile_index = 0; profile_index < profiles.size(); profile_index++) {
            if (requested_profile >= 0 && profile_index != static_cast<size_t>(requested_profile)) continue;
            const Profile& profile = profiles[profile_index];
            for (int duration : durations) {
                if (requested_duration != 0 && duration != requested_duration) continue;
                std::vector<double> final_errors, drift_ratios;
                int outputs = 0, successes = 0, available = 0, unavailable_ends = 0;
                for (int repeat = 0; repeat < repeats; repeat++) {
                    const uint64_t seed = 0xBEEFu + repeat * 7919u;
                    const Score score = run(profile, duration, seed, directory, algorithm);
                    require(score.outputs == duration * 10 + 1, "The scored timeline must include every expected output");
                    outputs += score.outputs;
                    available += score.available;
                    successes += score.within_ten;
                    unavailable_ends += !std::isfinite(score.final_error);
                    final_errors.push_back(std::isfinite(score.final_error) ? score.final_error : std::numeric_limits<double>::infinity());
                    if (score.distance >= 1) drift_ratios.push_back(final_errors.back() / score.distance);
                    std::printf("{\"type\":\"run\",\"profile\":\"%s\",\"algorithm\":\"%s\",\"seed\":%llu,\"durationSeconds\":%d,\"pathMeters\":%.8f,\"outputs\":%d,\"available\":%d,\"within5Meters\":%d,\"within10Meters\":%d,\"jointSuccess\":%.8f,\"finalErrorMeters\":%s,\"alongErrorMeters\":%s,\"crossErrorMeters\":%s,\"conditionalErrorP90Meters\":%s,\"conditionalSpeedErrorP90Mps\":%s,\"radiusCovered\":%d,\"radiusCount\":%d,\"peakInputAcceleration\":%.8f,\"peakInputGyro\":%.8f,\"clippedSamples\":%d,\"droppedSamples\":%d,\"pointTargetMet\":%s,\"carProfileApplicable\":%s}\n",
                        profile.name, algorithm.c_str(), static_cast<unsigned long long>(seed), duration, score.distance,
                        score.outputs, score.available, score.within_five, score.within_ten, score.success_rate(),
                        number(score.final_error).c_str(), number(score.final_along).c_str(), number(score.final_cross).c_str(),
                        number(percentile(score.errors, 0.9)).c_str(), number(percentile(score.speed_errors, 0.9)).c_str(),
                        score.covered, score.radii, score.peak_acceleration, score.peak_rotation, score.clipped_samples,
                        score.dropped_samples, score.meets_point_target() ? "true" : "false", profile.lean ? "false" : "true");
                    std::fflush(stdout);
                }
                const double joint = outputs ? static_cast<double>(successes) / outputs : 0;
                const double final_p90 = percentile(final_errors, 0.9);
                const double drift_p90 = percentile(drift_ratios, 0.9);
                const bool passed = joint >= 0.9 && unavailable_ends == 0 && !(algorithm == "car" && profile.lean) &&
                    (profile.stopped ? final_p90 < 5 : drift_p90 < 0.1);
                failed_cases += !passed;
                std::printf("{\"type\":\"summary\",\"profile\":\"%s\",\"algorithm\":\"%s\",\"durationSeconds\":%d,\"runs\":%d,\"outputs\":%d,\"available\":%d,\"jointSuccess\":%.8f,\"finalErrorP90Meters\":%s,\"driftP90\":%s,\"unavailableEnds\":%d,\"benchmarkTargetMet\":%s,\"releaseApproved\":false}\n",
                    profile.name, algorithm.c_str(), duration, repeats, outputs, available, joint,
                    number(final_p90).c_str(), number(drift_p90).c_str(), unavailable_ends, passed ? "true" : "false");
            }
        }
        return failed_cases == 0 ? 0 : 1;
    } catch (const std::exception& failure) {
        std::fprintf(stderr, "%s\n", failure.what());
        return 2;
    }
}
