#include "setu_filter.h"
#include "filter_state.h"
#include <Eigen/Core>
#include <Eigen/Cholesky>
#include <Eigen/LU>
#include <Eigen/SVD>
#include <algorithm>
#include <cmath>
#include <limits>
#include <new>

namespace {
Matrix3 hat(const Vector3& vector) {
    Matrix3 result;
    result << 0, -vector.z(), vector.y(), vector.z(), 0, -vector.x(), -vector.y(), vector.x(), 0;
    return result;
}

Matrix3 exponential(const Vector3& vector) {
    const double angle = vector.norm();
    const double squared = angle * angle;
    const double sine = angle < 1e-7 ? 1 - squared / 6 + squared * squared / 120 : std::sin(angle) / angle;
    const double cosine = angle < 1e-7 ? 0.5 - squared / 24 + squared * squared / 720 : (1 - std::cos(angle)) / squared;
    const Matrix3 skew = hat(vector);
    return Matrix3::Identity() + sine * skew + cosine * skew * skew;
}

Matrix3 left_jacobian(const Vector3& vector) {
    const double angle = vector.norm();
    const double squared = angle * angle;
    const double second = angle < 1e-7 ? 0.5 - squared / 24 : (1 - std::cos(angle)) / squared;
    const double third = angle < 1e-7 ? 1.0 / 6 - squared / 120 : (angle - std::sin(angle)) / (squared * angle);
    const Matrix3 skew = hat(vector);
    return Matrix3::Identity() + second * skew + third * skew * skew;
}

Matrix3 normalize(const Matrix3& rotation) {
    const Eigen::JacobiSVD<Matrix3> decomposition(rotation, Eigen::ComputeFullU | Eigen::ComputeFullV);
    Matrix3 correction = Matrix3::Identity();
    correction(2, 2) = (decomposition.matrixU() * decomposition.matrixV().transpose()).determinant();
    return decomposition.matrixU() * correction * decomposition.matrixV().transpose();
}

bool finite(const double* values, int count) {
    if (!values) return false;
    for (int index = 0; index < count; ++index) {
        if (!std::isfinite(values[index])) return false;
    }
    return true;
}

bool valid(const SetuFilter& filter) {
    return filter.rotation.allFinite() && filter.position.allFinite() && filter.velocity.allFinite()
        && filter.gyro_bias.allFinite() && filter.accel_bias.allFinite()
        && filter.covariance.allFinite() && std::isfinite(filter.scale) && std::isfinite(filter.seconds);
}

template<int Dimension>
int apply(SetuFilter& filter, const Eigen::Matrix<double, Dimension, 1>& residual,
          const Eigen::Matrix<double, Dimension, 16>& jacobian,
          const double* standard_deviations, double* nis) {
    using MeasurementMatrix = Eigen::Matrix<double, Dimension, Dimension>;
    const MeasurementMatrix noise = Eigen::Map<const Eigen::Matrix<double, Dimension, 1>>(standard_deviations)
        .array().square().matrix().asDiagonal();
    const MeasurementMatrix innovation = jacobian * filter.covariance * jacobian.transpose() + noise;
    const Eigen::LDLT<MeasurementMatrix> decomposition(innovation);
    if (decomposition.info() != Eigen::Success || !decomposition.isPositive()) return -1;
    *nis = residual.dot(decomposition.solve(residual));
    if (!std::isfinite(*nis) || *nis < -1e-10) return -1;
    if (*nis > 16.0 * Dimension) return 0;
    const Eigen::Matrix<double, 16, Dimension> gain = decomposition.solve(jacobian * filter.covariance).transpose();
    const Vector16 correction = gain * residual;
    SetuFilter updated = filter;
    const Matrix3 rotation_delta = exponential(correction.head<3>());
    const Matrix3 translation_delta = left_jacobian(correction.head<3>());
    updated.rotation = normalize(rotation_delta * filter.rotation);
    updated.velocity = rotation_delta * filter.velocity + translation_delta * correction.segment<3>(3);
    updated.position = rotation_delta * filter.position + translation_delta * correction.segment<3>(6);
    updated.gyro_bias += correction.segment<3>(9);
    updated.accel_bias += correction.segment<3>(12);
    updated.scale = std::clamp(updated.scale + correction(15), 0.5, 6.0);
    const Matrix16 projection = Matrix16::Identity() - gain * jacobian;
    updated.covariance = projection * filter.covariance * projection.transpose() + gain * noise * gain.transpose();
    updated.covariance = (0.5 * (updated.covariance + updated.covariance.transpose())).eval();
    if (!valid(updated)) return -1;
    filter = updated;
    return 1;
}
}

SetuFilter* setu_filter_create(void) { return new (std::nothrow) SetuFilter; }
void setu_filter_destroy(SetuFilter* filter) { delete filter; }

int setu_filter_reset(SetuFilter* filter, const double rotation[9], const double position[3],
                      const double velocity[3], const double standard_deviations[6], double scale) {
    if (!filter || !finite(rotation, 9) || !finite(position, 3) || !finite(velocity, 3)
        || !finite(standard_deviations, 6) || !std::isfinite(scale) || scale < 0.5 || scale > 6) return -1;
    const Matrix3 attitude = Eigen::Map<const RowMatrix3>(rotation);
    if ((attitude * attitude.transpose() - Matrix3::Identity()).norm() > 1e-5
        || std::abs(attitude.determinant() - 1) > 1e-5) return -1;
    for (int index = 0; index < 6; ++index) {
        if (standard_deviations[index] <= 0 || standard_deviations[index] > 10000) return -1;
    }
    SetuFilter initialized;
    initialized.rotation = normalize(attitude);
    initialized.position = Eigen::Map<const Vector3>(position);
    initialized.velocity = Eigen::Map<const Vector3>(velocity);
    initialized.covariance.setZero();
    for (int index = 0; index < 16; ++index) {
        const double deviation = standard_deviations[std::min(index / 3, 5)];
        initialized.covariance(index, index) = deviation * deviation;
    }
    initialized.scale = scale;
    initialized.initialized = true;
    *filter = initialized;
    return 1;
}

int setu_filter_propagate(SetuFilter* filter, const double acceleration[3], const double angular_rate[3],
                          double seconds, double noise_scale) {
    if (!filter || !filter->initialized || !finite(acceleration, 3) || !finite(angular_rate, 3)
        || !std::isfinite(seconds) || seconds <= 0 || seconds > 0.25
        || !std::isfinite(noise_scale) || noise_scale <= 0 || noise_scale > 100) return -1;
    const Vector3 accel = Eigen::Map<const Vector3>(acceleration);
    const Vector3 gyro = Eigen::Map<const Vector3>(angular_rate);
    if (accel.norm() > 200 || gyro.norm() > 100) return -1;
    const Vector3 accel_mid = filter->has_previous ? (0.5 * (accel + filter->previous_accel)).eval() : accel;
    const Vector3 gyro_mid = filter->has_previous ? (0.5 * (gyro + filter->previous_gyro)).eval() : gyro;
    const Vector3 gravity(0, 0, -9.80665);
    const Matrix3 rotation = filter->rotation;
    const Vector3 velocity = filter->velocity;
    const Vector3 position = filter->position;
    const Matrix3 rotation_mid = rotation * exponential((gyro_mid - filter->gyro_bias) * (0.5 * seconds));
    const Vector3 acceleration_nav = rotation_mid * (accel_mid - filter->accel_bias) + gravity;
    SetuFilter propagated = *filter;
    propagated.rotation = normalize(rotation * exponential((gyro_mid - filter->gyro_bias) * seconds));
    propagated.velocity += acceleration_nav * seconds;
    propagated.position += velocity * seconds + 0.5 * acceleration_nav * seconds * seconds;
    Matrix16 dynamics = Matrix16::Zero();
    dynamics.block<3, 3>(3, 0) = hat(gravity);
    dynamics.block<3, 3>(6, 3) = Matrix3::Identity();
    dynamics.block<3, 3>(0, 9) = -rotation;
    dynamics.block<3, 3>(3, 9) = -hat(velocity) * rotation;
    dynamics.block<3, 3>(3, 12) = -rotation;
    dynamics.block<3, 3>(6, 9) = -hat(position) * rotation;
    const Matrix16 transition = Matrix16::Identity() + dynamics * seconds + 0.5 * dynamics * dynamics * seconds * seconds;
    Matrix16 noise = Matrix16::Zero();
    const double gyro_noise = 3.4e-4 * 3.4e-4 * seconds * noise_scale;
    const double accel_noise = 4.2e-3 * 4.2e-3 * seconds * noise_scale;
    noise.block<3, 3>(0, 0) = gyro_noise * rotation * rotation.transpose();
    noise.block<3, 3>(3, 3) = accel_noise * rotation * rotation.transpose() + gyro_noise * hat(velocity) * hat(velocity).transpose();
    noise.block<3, 3>(6, 6) = gyro_noise * hat(position) * hat(position).transpose() + 1e-12 * Matrix3::Identity();
    noise.block<3, 3>(9, 9) = 5e-5 * 5e-5 * seconds * Matrix3::Identity();
    noise.block<3, 3>(12, 12) = 1.6e-3 * 1.6e-3 * seconds * Matrix3::Identity();
    noise(15, 15) = 2e-5 * 2e-5 * seconds;
    propagated.covariance = transition * filter->covariance * transition.transpose() + noise;
    propagated.covariance = (0.5 * (propagated.covariance + propagated.covariance.transpose())).eval();
    propagated.seconds += seconds;
    propagated.previous_accel = accel;
    propagated.previous_gyro = gyro;
    propagated.has_previous = true;
    if (!valid(propagated)) return -1;
    *filter = propagated;
    return 1;
}

int setu_filter_update(SetuFilter* filter, int kind, const double* measurement,
                       const double* standard_deviations, int dimension, double* nis) {
    if (nis) *nis = std::numeric_limits<double>::infinity();
    if (!filter || !filter->initialized || !nis || dimension < 1 || dimension > 3
        || !finite(measurement, dimension) || !finite(standard_deviations, dimension)) return -1;
    for (int index = 0; index < dimension; ++index) {
        if (standard_deviations[index] <= 0 || standard_deviations[index] > 10000) return -1;
    }
    Eigen::Matrix<double, 3, 16> jacobian = Eigen::Matrix<double, 3, 16>::Zero();
    Vector3 residual = Vector3::Zero();
    if (kind == SETU_POSITION || kind == SETU_POSITION_2D || kind == SETU_ALTITUDE) {
        const int expected = kind == SETU_POSITION ? 3 : kind == SETU_POSITION_2D ? 2 : 1;
        if (dimension != expected) return -1;
        const Eigen::Matrix<double, 3, 3> attitude_jacobian = -hat(filter->position);
        for (int index = 0; index < dimension; ++index) {
            const int axis = kind == SETU_ALTITUDE ? 2 : index;
            jacobian.block<1, 3>(index, 0) = attitude_jacobian.row(axis);
            jacobian(index, 6 + axis) = 1;
            residual(index) = measurement[index] - filter->position(axis);
        }
    } else if (kind == SETU_VELOCITY || kind == SETU_VELOCITY_2D) {
        if (dimension != (kind == SETU_VELOCITY ? 3 : 2)) return -1;
        jacobian.block<3, 3>(0, 0) = -hat(filter->velocity);
        jacobian.block<3, 3>(0, 3) = Matrix3::Identity();
        for (int index = 0; index < dimension; ++index) residual(index) = measurement[index] - filter->velocity(index);
    } else if (kind >= SETU_FORWARD_SPEED && kind <= SETU_SVO_FREQUENCY) {
        const int expected = kind == SETU_ZUPT ? 3 : kind == SETU_NHC ? 2 : 1;
        if (dimension != expected) return -1;
        const Vector3 body_velocity = filter->rotation.transpose() * filter->velocity;
        const Matrix3 inverse_rotation = filter->rotation.transpose();
        for (int index = 0; index < dimension; ++index) {
            const int axis = kind == SETU_NHC ? index + 1 : index;
            jacobian.block<1, 3>(index, 3) = inverse_rotation.row(axis);
            residual(index) = (kind == SETU_NHC || kind == SETU_ZUPT ? 0 : measurement[index]) - body_velocity(axis);
        }
        if (kind == SETU_SVO_FREQUENCY) {
            jacobian.row(0) /= filter->scale;
            jacobian(0, 15) = -body_velocity.x() / (filter->scale * filter->scale);
            residual(0) = measurement[0] - body_velocity.x() / filter->scale;
        }
    } else return -1;
    if (dimension == 1) return apply<1>(*filter, residual.head<1>(), jacobian.topRows<1>(), standard_deviations, nis);
    if (dimension == 2) return apply<2>(*filter, residual.head<2>(), jacobian.topRows<2>(), standard_deviations, nis);
    return apply<3>(*filter, residual, jacobian, standard_deviations, nis);
}

int setu_filter_snapshot(const SetuFilter* filter, double output[SETU_SNAPSHOT_SIZE]) {
    if (!filter || !filter->initialized || !output) return -1;
    Eigen::Map<RowMatrix3> rotation(output);
    rotation = filter->rotation;
    Eigen::Map<Vector3> velocity(output + 9);
    velocity = filter->velocity;
    Eigen::Map<Vector3> position(output + 12);
    position = filter->position;
    Eigen::Map<Vector3> gyro_bias(output + 15);
    gyro_bias = filter->gyro_bias;
    Eigen::Map<Vector3> accel_bias(output + 18);
    accel_bias = filter->accel_bias;
    output[21] = filter->scale;
    output[22] = filter->seconds;
    Eigen::Map<Eigen::Matrix<double, 16, 16, Eigen::RowMajor>> covariance(output + 23);
    covariance = filter->covariance;
    return 1;
}
