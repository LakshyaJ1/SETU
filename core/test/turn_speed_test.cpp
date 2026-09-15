#include "turn_speed_candidate.h"
#include <cstdio>
#include <limits>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

SetuFilter state_at(double heading, double bank, double grade, const Matrix3& mount) {
    SetuFilter state;
    state.rotation = (Eigen::AngleAxisd(heading, Vector3::UnitZ()) *
        Eigen::AngleAxisd(grade, Vector3::UnitX()) *
        Eigen::AngleAxisd(bank, Vector3::UnitY())).toRotationMatrix() * mount.transpose();
    state.accel_bias = Vector3(.1, -.2, .15);
    state.gyro_bias = Vector3(.003, -.004, .002);
    state.covariance.setZero();
    return state;
}

std::optional<TurnSpeed> observe(const SetuFilter& state, const Vector3& forward_body,
                                double speed, double turn, double roll_rate,
                                double vertical_shock, double deviation = .25) {
    const Vector3 forward_world = state.rotation * forward_body;
    const Vector3 angular_world = turn * Vector3::UnitZ() + roll_rate * forward_world;
    const Vector3 force_world = speed * angular_world.cross(forward_world) +
        1.5 * forward_world + (9.80665 + vertical_shock) * Vector3::UnitZ();
    return coordinated_turn_speed(state, state.rotation.transpose() * force_world + state.accel_bias,
        state.rotation.transpose() * angular_world + state.gyro_bias, forward_body, deviation);
}
}

int main() {
    try {
        const Matrix3 mount = (Eigen::AngleAxisd(.7, Vector3::UnitX()) *
            Eigen::AngleAxisd(-1.2, Vector3::UnitY()) *
            Eigen::AngleAxisd(.4, Vector3::UnitZ())).toRotationMatrix();
        const Vector3 forward = mount * Vector3::UnitY();
        int cases = 0;
        for (double heading : {-2.4, 0.0, 1.7}) {
            for (double bank : {-.6, 0.0, .6}) {
                for (double grade : {-.25, 0.0, .25}) {
                    for (double turn : {-.2, .2}) {
                        for (double shock : {-40.0, 0.0, 40.0}) {
                            const auto state = state_at(heading, bank, grade, mount);
                            const auto result = observe(state, forward, 12, turn, .3, shock);
                            require(result && std::abs(result->speed - 12) < 1e-9,
                                "Turn speed must ignore bank, grade, roll, mount, bias and vertical shock");
                            cases++;
                        }
                    }
                }
            }
        }
        auto state = state_at(0, .4, 0, mount);
        require(!observe(state, forward, 12, 0, 1, 0), "Pure roll must not become a vehicle turn");
        require(!observe(state, forward, 12, .001, 0, 0), "Near-zero turn rate is unobservable");
        require(!observe(state, forward, -12, .2, 0, 0), "Opposite force cannot become positive speed");
        require(!observe(state, forward, 70, .2, 0, 0), "Reject out-of-range turn speed");
        require(!observe(state_at(0, 0, .8, mount), forward, 12, .2, 0, 0),
            "Reject poorly conditioned near-vertical forward axes");
        const auto baseline = observe(state, forward, 12, .2, 0, 0);
        const auto rough = observe(state, forward, 12, .2, 0, 0, 3.0);
        require(baseline && rough && rough->sigma > baseline->sigma,
            "Roughness must increase uncertainty instead of looking like precise speed");
        state.covariance(0, 0) = .001;
        state.covariance(1, 1) = .001;
        state.covariance(9, 9) = .0001;
        state.covariance(12, 12) = .01;
        const auto uncertain = observe(state, forward, 12, .2, 0, 0);
        const auto shocked = observe(state, forward, 12, .2, 0, 40);
        require(uncertain && shocked && uncertain->sigma > baseline->sigma &&
            shocked->sigma > uncertain->sigma, "Tilt and bias uncertainty must include gravity/shock leakage");
        const double invalid = std::numeric_limits<double>::quiet_NaN();
        require(!coordinated_turn_speed(state, Vector3(invalid, 0, 0), Vector3::Zero(), forward, .25),
            "Non-finite sensors must be rejected");
        require(!observe(state, forward, 12, .2, 0, 0, -1), "Negative noise must be rejected");
        require(!observe(state, forward * 2, 12, .2, 0, 0), "Mount axis must be normalized");
        std::printf("{\"type\":\"turn_speed_self_test\",\"passed\":true,\"physicsCases\":%d,\"guardChecks\":10}\n", cases);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
