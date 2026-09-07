#pragma once
#include <Eigen/Core>

using Vector3 = Eigen::Vector3d;
using Matrix3 = Eigen::Matrix3d;
using Matrix16 = Eigen::Matrix<double, 16, 16>;
using Vector16 = Eigen::Matrix<double, 16, 1>;
using RowMatrix3 = Eigen::Matrix<double, 3, 3, Eigen::RowMajor>;

struct SetuFilter {
    Matrix3 rotation = Matrix3::Identity();
    Vector3 velocity = Vector3::Zero();
    Vector3 position = Vector3::Zero();
    Vector3 gyro_bias = Vector3::Zero();
    Vector3 accel_bias = Vector3::Zero();
    Matrix16 covariance = Matrix16::Identity();
    Vector3 previous_accel = Vector3::Zero();
    Vector3 previous_gyro = Vector3::Zero();
    double scale = 1.7467;
    double seconds = 0;
    bool initialized = false;
    bool has_previous = false;
};
