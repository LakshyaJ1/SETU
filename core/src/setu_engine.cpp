#include "setu_engine.h"
#include "setu_filter.h"
#include "filter_state.h"
#include <GeographicLib/LocalCartesian.hpp>
#include <GeographicLib/MagneticModel.hpp>
#include <Eigen/LU>
#include <Eigen/Geometry>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numbers>

namespace {
constexpr int capacity = 512;
constexpr int64_t history_ns = 2000000000;
constexpr int64_t maximum_gap_ns = 100000000;
constexpr double radians = std::numbers::pi / 180;
struct Frame {
    int64_t timestamp = 0;
    Vector3 acceleration = Vector3::Zero();
    Vector3 gyro = Vector3::Zero();
    SetuFilter state;
};
struct Fix {
    int64_t timestamp = 0;
    std::array<double, 10> values{};
};
bool finite(const double* data, int length) {
    if (!data) return false;
    for (int index = 0; index < length; ++index) if (!std::isfinite(data[index])) return false;
    return true;
}
bool optional(double value, double minimum, double maximum) {
    return std::isnan(value) || (std::isfinite(value) && value >= minimum && value <= maximum);
}
double position_sigma(const Fix& fix) { return std::max(2.0, fix.values[3] / std::sqrt(-2 * std::log(0.32))); }
bool velocity_available(const Fix& fix) {
    return std::isfinite(fix.values[5]) && std::isfinite(fix.values[6]) &&
        std::isfinite(fix.values[7]) && std::isfinite(fix.values[8]) && fix.values[8] < 45;
}
Vector3 velocity(const Fix& fix) {
    const double course = fix.values[6] * radians;
    return {fix.values[5] * std::sin(course), fix.values[5] * std::cos(course), 0};
}
double velocity_sigma(const Fix& fix) {
    return std::max(0.5, std::hypot(fix.values[7], fix.values[5] * fix.values[8] * radians));
}
double radius(const SetuFilter& state) {
    Eigen::Matrix<double, 2, 16> projection = Eigen::Matrix<double, 2, 16>::Zero();
    projection(0, 1) = state.position.z();
    projection(0, 2) = -state.position.y();
    projection(1, 0) = -state.position.z();
    projection(1, 2) = state.position.x();
    projection(0, 6) = 1;
    projection(1, 7) = 1;
    const Eigen::Matrix2d covariance = projection * state.covariance * projection.transpose();
    const double eigenvalue = 0.5 * (covariance.trace() + std::hypot(covariance(0, 0) - covariance(1, 1), 2 * covariance(0, 1)));
    return std::sqrt(5.991464547 * std::max(0.0, eigenvalue));
}
}

struct SetuEngine {
    GeographicLib::MagneticModel magnetic;
    GeographicLib::LocalCartesian coordinates;
    std::array<Frame, capacity> frames;
    int head = 0;
    int count = 0;
    Frame corrected;
    bool has_correction = false;
    Fix pending;
    int64_t last_fix_seen = 0;
    int64_t accepted_fix_ns = 0;
    int64_t attitude_ns = 0;
    RowMatrix3 attitude = RowMatrix3::Identity();
    double attitude_sigma = 1;
    bool initialized = false;
    bool altitude_known = false;
    double origin_altitude = 0;
    double mock = std::numeric_limits<double>::quiet_NaN();
    int status = 0;
    int accepted = 0;
    int gated = 0;
    int rejected = 0;
    int replays = 0;
    int resets = 0;
    double last_nis = 0;

    explicit SetuEngine(const char* path) : magnetic("wmm2025", path) {}
    Frame& at(int index) { return frames[(head + index) % capacity]; }
    const Frame& at(int index) const { return frames[(head + index) % capacity]; }
    void append(const Frame& frame) {
        if (count == capacity) { head = (head + 1) % capacity; --count; }
        at(count++) = frame;
        while (count > 1 && at(count - 1).timestamp - at(0).timestamp > history_ns) { head = (head + 1) % capacity; --count; }
    }
    void invalidate(int reason) {
        initialized = false;
        has_correction = false;
        head = 0;
        count = 0;
        pending.timestamp = 0;
        status = reason;
        ++resets;
    }
};

namespace {
bool advance(Frame& frame, const Frame& destination, int64_t timestamp) {
    if (timestamp == frame.timestamp) return true;
    if (timestamp < frame.timestamp || destination.timestamp < timestamp || destination.timestamp == frame.timestamp) return false;
    const double fraction = static_cast<double>(timestamp - frame.timestamp) / (destination.timestamp - frame.timestamp);
    const Vector3 acceleration = frame.acceleration + fraction * (destination.acceleration - frame.acceleration);
    const Vector3 gyro = frame.gyro + fraction * (destination.gyro - frame.gyro);
    if (setu_filter_propagate(&frame.state, acceleration.data(), gyro.data(), (timestamp - frame.timestamp) * 1e-9, 4.0) != 1) return false;
    frame.acceleration = acceleration;
    frame.gyro = gyro;
    frame.timestamp = timestamp;
    return true;
}
bool initialize(SetuEngine& engine) {
    if (!engine.count || !engine.pending.timestamp) return false;
    Frame& current = engine.at(engine.count - 1);
    const Fix& fix = engine.pending;
    if (current.timestamp < fix.timestamp || current.timestamp - fix.timestamp > 250000000) { engine.status = 0; return false; }
    if (!engine.attitude_ns || std::abs(current.timestamp - engine.attitude_ns) > 250000000 || engine.attitude_sigma > 0.6) {
        engine.status = 1; return false;
    }
    engine.altitude_known = std::isfinite(fix.values[2]) && std::isfinite(fix.values[4]);
    engine.origin_altitude = engine.altitude_known ? fix.values[2] : 0;
    engine.coordinates.Reset(fix.values[0], fix.values[1], engine.origin_altitude);
    const bool has_velocity = velocity_available(fix);
    const Vector3 initial_velocity = has_velocity ? velocity(fix) : Vector3::Zero();
    const double lag = (current.timestamp - fix.timestamp) * 1e-9;
    const Vector3 initial_position = initial_velocity * lag;
    const double alignment_lag = (current.timestamp - engine.attitude_ns) * 1e-9;
    RowMatrix3 aligned = engine.attitude;
    if (current.gyro.norm() > 1e-10) aligned = engine.attitude * Eigen::AngleAxisd(current.gyro.norm() * alignment_lag, current.gyro.normalized()).toRotationMatrix();
    const double deviations[6] = {std::hypot(std::max(0.15, engine.attitude_sigma), current.gyro.norm() * alignment_lag), 10.0,
        std::hypot(position_sigma(fix), 30.0 * lag), 0.03, 0.15, 0.05};
    if (setu_filter_reset(&current.state, aligned.data(), initial_position.data(), initial_velocity.data(), deviations, 1.7467) != 1) return false;
    current.state.covariance(8, 8) = engine.altitude_known ? std::pow(std::max(5.0, fix.values[4]), 2) : 10000;
    current.state.previous_accel = current.acceleration;
    current.state.previous_gyro = current.gyro;
    current.state.has_previous = true;
    Frame seed = current;
    engine.head = 0;
    engine.count = 0;
    engine.append(seed);
    engine.initialized = true;
    engine.accepted_fix_ns = fix.timestamp;
    engine.mock = fix.values[9];
    engine.pending.timestamp = 0;
    engine.status = 2;
    ++engine.accepted;
    return true;
}
int correct(SetuEngine& engine, const Fix& fix) {
    if (!engine.count || fix.timestamp < engine.at(0).timestamp ||
        (engine.has_correction && fix.timestamp < engine.corrected.timestamp)) { ++engine.rejected; return 0; }
    int previous = 0;
    while (previous + 1 < engine.count && engine.at(previous + 1).timestamp <= fix.timestamp) ++previous;
    Frame checkpoint = engine.at(previous);
    if (engine.has_correction && engine.corrected.timestamp > checkpoint.timestamp) checkpoint = engine.corrected;
    if (checkpoint.timestamp < fix.timestamp && (previous + 1 >= engine.count || !advance(checkpoint, engine.at(previous + 1), fix.timestamp))) {
        ++engine.rejected; return 0;
    }
    double position[3];
    const bool has_altitude = std::isfinite(fix.values[2]) && std::isfinite(fix.values[4]);
    engine.coordinates.Forward(fix.values[0], fix.values[1], has_altitude ? fix.values[2] : engine.origin_altitude,
        position[0], position[1], position[2]);
    const double sigma = position_sigma(fix);
    const double uncertainty[2] = {sigma, sigma};
    const int result = setu_filter_update(&checkpoint.state, SETU_POSITION_2D, position, uncertainty, 2, &engine.last_nis);
    if (result != 1) { result == 0 ? ++engine.gated : ++engine.rejected; return result; }
    if (has_altitude && engine.altitude_known) {
        const double vertical_sigma = std::max(5.0, fix.values[4]);
        double ignored;
        setu_filter_update(&checkpoint.state, SETU_ALTITUDE, position + 2, &vertical_sigma, 1, &ignored);
    }
    if (velocity_available(fix)) {
        const Vector3 speed = velocity(fix);
        const double speed_sigma = velocity_sigma(fix);
        const double velocity_uncertainty[2] = {speed_sigma, speed_sigma};
        double ignored;
        setu_filter_update(&checkpoint.state, SETU_VELOCITY_2D, speed.data(), velocity_uncertainty, 2, &ignored);
    }
    engine.corrected = checkpoint;
    engine.has_correction = true;
    if (engine.at(previous).timestamp == fix.timestamp) engine.at(previous) = checkpoint;
    for (int index = previous + 1; index < engine.count; ++index) {
        const Frame target = engine.at(index);
        if (!advance(checkpoint, target, target.timestamp)) { engine.invalidate(4); return -1; }
        engine.at(index) = checkpoint;
    }
    engine.accepted_fix_ns = fix.timestamp;
    engine.mock = engine.mock == 1 || fix.values[9] == 1 ? 1 :
        (engine.mock == 0 && fix.values[9] == 0 ? 0 : std::numeric_limits<double>::quiet_NaN());
    ++engine.accepted;
    if (fix.timestamp < engine.at(engine.count - 1).timestamp) ++engine.replays;
    return 1;
}
}

SetuEngine* setu_engine_create(const char* directory) {
    if (!directory) return nullptr;
    try { return new SetuEngine(directory); } catch (...) { return nullptr; }
}
void setu_engine_destroy(SetuEngine* engine) { delete engine; }

int setu_engine_attitude(SetuEngine* engine, int64_t timestamp, const double rotation[9], double sigma) {
    if (!engine || timestamp <= engine->attitude_ns || !finite(rotation, 9) || !std::isfinite(sigma) || sigma < 0 || sigma > 0.6) return -1;
    const RowMatrix3 matrix = Eigen::Map<const RowMatrix3>(rotation);
    if ((matrix * matrix.transpose() - Matrix3::Identity()).norm() > 1e-5 || std::abs(matrix.determinant() - 1) > 1e-5) return -1;
    engine->attitude = matrix;
    engine->attitude_ns = timestamp;
    engine->attitude_sigma = sigma;
    if (!engine->initialized) initialize(*engine);
    return 1;
}

int setu_engine_imu(SetuEngine* engine, int64_t timestamp, const double acceleration[3], const double gyro[3]) {
    if (!engine || timestamp <= 0) return -1;
    if (!finite(acceleration, 3) || !finite(gyro, 3)) { ++engine->rejected; engine->invalidate(4); return -1; }
    if (engine->count && timestamp <= engine->at(engine->count - 1).timestamp) { ++engine->rejected; return 0; }
    if (Eigen::Map<const Vector3>(acceleration).norm() > 200 || Eigen::Map<const Vector3>(gyro).norm() > 100) {
        ++engine->rejected; engine->invalidate(4); return -1;
    }
    Frame current;
    current.timestamp = timestamp;
    current.acceleration = Eigen::Map<const Vector3>(acceleration);
    current.gyro = Eigen::Map<const Vector3>(gyro);
    if (engine->count && timestamp - engine->at(engine->count - 1).timestamp > maximum_gap_ns) engine->invalidate(4);
    if (engine->initialized) {
        Frame propagated = engine->at(engine->count - 1);
        if (!advance(propagated, current, timestamp)) { engine->invalidate(4); return -1; }
        current.state = propagated.state;
    }
    engine->append(current);
    if (!engine->initialized) initialize(*engine);
    else if (engine->pending.timestamp && engine->pending.timestamp <= timestamp) {
        const Fix pending = engine->pending;
        engine->pending.timestamp = 0;
        correct(*engine, pending);
    }
    if (engine->initialized && (timestamp - engine->accepted_fix_ns > 10000000000LL || radius(engine->at(engine->count - 1).state) > 150)) {
        engine->invalidate(5);
    }
    return 1;
}

int setu_engine_gnss(SetuEngine* engine, int64_t timestamp, const double values[10]) {
    if (!engine || !values || timestamp <= 0 || !finite(values, 2) || std::abs(values[0]) > 90 || std::abs(values[1]) > 180 ||
        !std::isfinite(values[3]) || values[3] < 0 || values[3] > 100 ||
        !optional(values[2], -1000, 20000) || !optional(values[4], 0, 1000) || !optional(values[5], 0, 100) ||
        !optional(values[6], 0, 359.999999999) || !optional(values[7], 0, 100) || !optional(values[8], 0, 3600) ||
        !(std::isnan(values[9]) || values[9] == 0 || values[9] == 1)) return -1;
    if (engine->count && timestamp - engine->at(engine->count - 1).timestamp > 250000000) { ++engine->rejected; return -1; }
    if (timestamp <= engine->last_fix_seen) { ++engine->rejected; return 0; }
    engine->last_fix_seen = timestamp;
    Fix fix;
    fix.timestamp = timestamp;
    std::copy(values, values + 10, fix.values.begin());
    if (!engine->initialized || !engine->count || timestamp > engine->at(engine->count - 1).timestamp) {
        engine->pending = fix;
        if (!engine->initialized) return initialize(*engine) ? 1 : 0;
        return 0;
    }
    return correct(*engine, fix);
}

int setu_engine_poll(const SetuEngine* engine, double output[SETU_ESTIMATE_SIZE]) {
    if (!engine || !output) return -1;
    std::fill(output, output + SETU_ESTIMATE_SIZE, std::numeric_limits<double>::quiet_NaN());
    output[0] = engine->status;
    output[10] = engine->accepted;
    output[11] = engine->gated;
    output[12] = engine->rejected;
    output[13] = engine->replays;
    output[14] = engine->resets;
    output[15] = engine->last_nis;
    if (!engine->initialized || !engine->count) return 0;
    const Frame& latest = engine->at(engine->count - 1);
    const double age = (latest.timestamp - engine->accepted_fix_ns) * 1e-9;
    output[0] = age <= 2 ? 2 : 3;
    output[1] = latest.timestamp * 1e-9;
    engine->coordinates.Reverse(latest.state.position.x(), latest.state.position.y(), latest.state.position.z(), output[2], output[3], output[4]);
    if (!engine->altitude_known) output[4] = std::numeric_limits<double>::quiet_NaN();
    output[5] = latest.state.velocity.head<2>().norm();
    output[6] = output[5] >= 1 ? std::fmod(std::atan2(latest.state.velocity.x(), latest.state.velocity.y()) / radians + 360, 360) : std::numeric_limits<double>::quiet_NaN();
    output[7] = radius(latest.state);
    output[8] = age;
    output[9] = engine->mock;
    output[16] = latest.state.velocity.x();
    output[17] = latest.state.velocity.y();
    output[18] = latest.state.position.x();
    output[19] = latest.state.position.y();
    return 1;
}

double setu_engine_declination(const SetuEngine* engine, double year, double latitude, double longitude, double altitude) {
    const double invalid = std::numeric_limits<double>::quiet_NaN();
    if (!engine || !std::isfinite(year) || year < 2025 || year >= 2030 || !std::isfinite(latitude) || std::abs(latitude) > 89 ||
        !std::isfinite(longitude) || std::abs(longitude) > 180 || !std::isfinite(altitude) || altitude < -1000 || altitude > 20000) return invalid;
    try {
        double east, north, up;
        engine->magnetic(year, latitude, longitude, altitude, east, north, up);
        if (std::hypot(east, north) < 2000) return invalid;
        return std::atan2(east, north);
    } catch (...) { return invalid; }
}
