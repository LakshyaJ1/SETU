#pragma once
#include "../src/filter_state.h"
#include <Eigen/Geometry>
#include <algorithm>
#include <cmath>
#include <optional>

struct TurnSpeed {
    double speed;
    double sigma;
};

inline std::optional<TurnSpeed> coordinated_turn_speed(
        const SetuFilter& state, const Vector3& acceleration, const Vector3& gyro,
        const Vector3& mount_forward, double force_deviation) {
    if (!state.rotation.allFinite() || !state.covariance.allFinite() ||
        !state.accel_bias.allFinite() || !state.gyro_bias.allFinite() ||
        !acceleration.allFinite() || !gyro.allFinite() || !mount_forward.allFinite() ||
        std::abs(mount_forward.norm() - 1.0) > 1e-3 ||
        !std::isfinite(force_deviation) || force_deviation < 0) return std::nullopt;
    const Vector3 forward = state.rotation * mount_forward;
    const double horizontal = forward.head<2>().norm();
    if (horizontal < .85) return std::nullopt;
    const Vector3 lateral = state.rotation.transpose() *
        (Vector3::UnitZ().cross(forward) / horizontal);
    const Vector3 turn_axis = mount_forward.cross(lateral);
    const Vector3 corrected_acceleration = acceleration - state.accel_bias;
    const Vector3 corrected_gyro = gyro - state.gyro_bias;
    const double turn = turn_axis.dot(corrected_gyro);
    if (std::abs(turn) < .05) return std::nullopt;
    const double force = lateral.dot(corrected_acceleration);
    const double speed = force / turn;
    if (!std::isfinite(speed) || speed < 0 || speed >= 60) return std::nullopt;
    const double tilt_variance = std::max(0.0, state.covariance(0, 0) + state.covariance(1, 1));
    const double force_variance = std::pow(std::max(.25, force_deviation), 2) +
        std::max(0.0, lateral.dot(state.covariance.block<3, 3>(12, 12) * lateral)) +
        corrected_acceleration.squaredNorm() * tilt_variance +
        std::pow(.09 * mount_forward.dot(corrected_acceleration), 2);
    const double turn_variance = 4e-6 +
        std::max(0.0, turn_axis.dot(state.covariance.block<3, 3>(9, 9) * turn_axis)) +
        corrected_gyro.squaredNorm() * (tilt_variance + .09 * .09);
    const double sigma = std::max(.8, std::sqrt(force_variance + speed * speed * turn_variance) /
        std::abs(turn));
    if (!std::isfinite(sigma)) return std::nullopt;
    return TurnSpeed{speed, sigma};
}
