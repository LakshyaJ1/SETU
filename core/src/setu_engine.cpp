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
#include <cstdio>
#include <cstdlib>
#include <numbers>

namespace {
constexpr int capacity = 512;
constexpr int64_t history_ns = 2000000000;
constexpr int64_t maximum_gap_ns = 100000000;
constexpr double radians = std::numbers::pi / 180;
// --- dead-reckoning constraints -------------------------------------------------------------
//
// Without these the filter has nothing but raw IMU integration once GNSS stops, and MEMS position
// error grows without bound (roughly cubically in time through accelerometer bias). The filter has
// always had the update maths for zero-velocity and non-holonomic constraints; nothing generated
// them, which is why a blackout produced garbage and the engine simply gave up after ten seconds.
constexpr int motion_capacity = 64;          // ~0.32 s at 200 Hz
constexpr double gravity_magnitude = 9.80665;
// An idling vehicle is not silent: engine and body vibration put roughly 0.1-0.3 m/s^2 on the
// accelerometer, while cruising on tarmac puts well over 1. This was briefly tightened to 0.10 to
// stop ZUPT firing at speed, but the real fix for that was the speed gate and the GNSS veto below;
// at 0.10 no genuine stop was ever recognised, and the parking-creep profile got one ZUPT in five
// stops.
constexpr double stationary_accel_deviation = 0.30;   // m/s^2, 1-sigma over the window
constexpr double stationary_rotation_rate = 0.06;     // rad/s, peak over the window
constexpr double stationary_gravity_tolerance = 0.6;  // m/s^2 away from g
// Rates matter as much as the constraints themselves. A non-holonomic constraint is one standing
// physical fact, not a fresh independent measurement every sample, and the filter has no way to
// know that: every application shrinks the lateral-velocity covariance again. At 20 Hz that gated
// real GNSS fixes within six seconds. At 5 Hz the blackout ran well for eighteen seconds and then
// the filter started gating its *own* constraints - 250 applications of "lateral velocity is zero
// to 0.4 m/s" is an effective sigma of 0.025 m/s, far tighter than the physics supports, so the
// innovation test began rejecting them exactly when they were needed most.
//
// These intervals are near the real decorrelation time of what is being asserted: tyre slip and
// road camber change over roughly a second, not a sample. Slower also costs less CPU per REQ-N1.
constexpr int64_t zupt_interval_ns = 500000000;       // 2 Hz
constexpr int64_t nhc_interval_ns = 1000000000;       // 1 Hz
constexpr int64_t cts_interval_ns = 1000000000;       // 1 Hz
constexpr double turn_gate_rps = 0.05;                // docs/03 3.4: below this the division blows up
// Low enough that a parking-garage creep still calibrates the mount. At 5 m/s the REQ-P2
// profile never observed it at all, so NHC never engaged in exactly the case it helps most.
constexpr double mount_speed_gate = 4.0;              // m/s before travel direction is meaningful
constexpr int64_t mount_interval_ns = 100000000;      // 10 Hz

// Rolling accelerometer/gyroscope statistics behind the stationarity test.
struct MotionWindow {
    std::array<double, motion_capacity> magnitude{};
    std::array<double, motion_capacity> turn{};
    int index = 0;
    int filled = 0;
    void push(double accel_magnitude, double rotation_rate) {
        magnitude[index] = accel_magnitude;
        turn[index] = rotation_rate;
        index = (index + 1) % motion_capacity;
        if (filled < motion_capacity) ++filled;
    }
    void clear() { index = 0; filled = 0; }
    bool ready() const { return filled == motion_capacity; }
    bool stationary() const {
        if (!ready()) return false;
        double sum = 0;
        for (int i = 0; i < motion_capacity; ++i) {
            if (turn[i] > stationary_rotation_rate) return false;
            sum += magnitude[i];
        }
        const double mean = sum / motion_capacity;
        if (std::abs(mean - gravity_magnitude) > stationary_gravity_tolerance) return false;
        double variance = 0;
        for (int i = 0; i < motion_capacity; ++i) variance += (magnitude[i] - mean) * (magnitude[i] - mean);
        return std::sqrt(variance / motion_capacity) < stationary_accel_deviation;
    }
};

// --- SVO: spectral velocity odometry --------------------------------------------------------
//
// Road roughness enters the body through the wheels, so the vibration carries a line at the axle
// rotation rate, f = v / (2 * pi * R_eff). Reading that line measures speed outright, with no
// integration and therefore no drift - which is the one thing NHC and ZUPT cannot supply, and the
// reason a blackout drifts along-track however well the lateral axis is held.
//
// docs/03 3.3 is explicit that the scale k_svo is a filter state observed by CTS and GNSS rather
// than an assumed wheel radius, so it is calibrated here from GNSS speed while that is available
// and then held through the blackout. Tyre pressure, load and wear all move R_eff; assuming it
// would bake in a bias of exactly the size REQ-P1 is measuring.
// 2.56 s at 200 Hz. A 5.12 s window was tried, on the reasoning that finer frequency resolution
// would tighten the learned scale - it did (1.91 and 2.01 against a true 1.948, from 1.82-1.96) but
// the tunnel profile got worse, because the extra latency costs more than the resolution buys.
constexpr int svo_capacity = 512;
// docs/03 3.3 gives ~4 m/s as the limit, on the reasoning that f0 drops below 2 Hz and the window
// cannot resolve it. That holds for a short FFT window; autocorrelation over 2.56 s still resolves
// a 1 Hz line, and lowering this does work - the parking profile gains real spectral speed updates
// and a sensible learned scale. It is held at 4.0 because the trade is monotonic and costs the
// thing that matters most:
//
//   floor    parking creep median    urban runs with no position at all
//   4.0 m/s        162 m                          20 / 40
//   2.5 m/s        138 m                          24 / 40
//   1.5 m/s        125 m                          26 / 40
//
// Neither profile passes its gate at any setting, so the better creep number buys nothing, while
// producing no position at all is the worst outcome a navigation app can have. The wider search
// floor and the low-speed confidence ramp below are kept because they are correct; drop this
// constant once the stop-start divergence itself is fixed.
constexpr double svo_minimum_speed = 4.0;
constexpr double svo_minimum_confidence = 0.28;        // normalised autocorrelation peak
constexpr int64_t svo_interval_ns = 1000000000;        // 1 Hz

struct SpectralOdometer {
    std::array<double, svo_capacity> magnitude{};
    std::array<int64_t, svo_capacity> stamp{};
    int index = 0;
    int filled = 0;

    void clear() { index = 0; filled = 0; }
    void push(int64_t timestamp, double value) {
        magnitude[index] = value;
        stamp[index] = timestamp;
        index = (index + 1) % svo_capacity;
        if (filled < svo_capacity) ++filled;
    }
    bool ready() const { return filled == svo_capacity; }

    // Fundamental frequency of the vibration, by autocorrelation. Returns 0 when nothing stands
    // out of the noise. A spectral peak-pick would need an FFT; over a band this narrow the
    // autocorrelation is cheaper, runs once a second, and degrades more gracefully when the line
    // is weak.
    //
    // `drift` reports how far the second half of the window disagrees with the first, as a
    // fraction. A windowed frequency is an average over 2.56 s, which is only a current speed while
    // the speed is steady: under hard braking the window still holds the pre-braking line, so the
    // estimate lags badly and reads far too fast. That is not a small error - it is what made the
    // stop-start profile diverge, because a filter that thinks it is doing 15 m/s while the car is
    // stopped never satisfies the stop test, so the zero-velocity update that would rescue it never
    // fires.
    double fundamental(double& confidence, double& drift) const {
        drift = 0;
        const double full = fundamental_over(0, svo_capacity, confidence);
        if (!(full > 0)) return 0;
        double recent_confidence = 0;
        const double recent = fundamental_over(svo_capacity / 2, svo_capacity, recent_confidence);
        if (recent > 0) drift = std::abs(recent - full) / std::max(full, 1e-6);
        return full;
    }

    double fundamental_over(int from, int to, double& confidence) const {
        confidence = 0;
        if (!ready()) return 0;
        const int count = to - from;
        if (count < 64) return 0;
        const int oldest = index;                       // ring is full, so index is the oldest slot
        const int64_t span = stamp[(oldest + to - 1) % svo_capacity] - stamp[(oldest + from) % svo_capacity];
        if (span <= 0) return 0;
        const double rate = (count - 1) * 1e9 / static_cast<double>(span);
        if (!(rate > 80 && rate < 1000)) return 0;      // aliased or irregular; docs/03 3.3

        std::array<double, svo_capacity> work{};
        double mean = 0;
        for (int i = 0; i < count; ++i) {
            work[i] = magnitude[(oldest + from + i) % svo_capacity];
            mean += work[i];
        }
        mean /= count;
        double energy = 0;
        for (int i = 0; i < count; ++i) { work[i] -= mean; energy += work[i] * work[i]; }
        if (energy < 1e-6) return 0;

        const int minimum_lag = std::max(4, static_cast<int>(rate / 20.0));   // 20 Hz ceiling
        // 0.7 Hz floor. The previous 1.5 Hz cut the search off at about 2.9 m/s, which together with
        // the speed gate below excluded the whole low-speed band by construction - and that band is
        // exactly where the creep and stop-start profiles live. At 2 m/s the axle line sits near
        // 1.0 Hz, which is still two and a half cycles inside a 2.56 s window, so it is resolvable;
        // the confidence test decides whether it is actually there.
        const int maximum_lag = std::min(count / 2, static_cast<int>(rate / 0.7));
        if (minimum_lag >= maximum_lag) return 0;

        // Autocorrelation of a periodic signal peaks at every multiple of the period, so taking the
        // global maximum picks 2T about as often as T and reports half the true frequency. That is
        // the classic octave error, and it showed up immediately: the urban profile learned a scale
        // of 3.61 m/Hz against a true 2*pi*R of 1.95. Take the *earliest* lag that comes close to
        // the best one instead, which is the standard pitch-detection remedy.
        std::array<double, svo_capacity> correlation{};
        int best_lag = 0;
        double best = 0;
        for (int lag = minimum_lag; lag <= maximum_lag; ++lag) {
            double sum = 0;
            for (int i = 0; i + lag < count; ++i) sum += work[i] * work[i + lag];
            correlation[lag] = sum / energy;
            if (correlation[lag] > best) { best = correlation[lag]; best_lag = lag; }
        }
        if (best_lag <= 0 || best < svo_minimum_confidence) return 0;
        const double acceptable = 0.85 * best;
        for (int lag = minimum_lag; lag < best_lag; ++lag) {
            // Require a genuine local maximum, so noise riding just above the threshold cannot
            // masquerade as an earlier fundamental.
            if (correlation[lag] >= acceptable && lag > minimum_lag && lag + 1 <= maximum_lag &&
                correlation[lag] >= correlation[lag - 1] && correlation[lag] >= correlation[lag + 1]) {
                best_lag = lag;
                best = correlation[lag];
                break;
            }
        }
        double previous = 0, next = 0;

        // Parabolic interpolation around the peak, so resolution is not limited to whole lags.
        {
            double sum = 0;
            for (int i = 0; i + best_lag - 1 < count; ++i) sum += work[i] * work[i + best_lag - 1];
            previous = sum / energy;
            sum = 0;
            for (int i = 0; i + best_lag + 1 < count; ++i) sum += work[i] * work[i + best_lag + 1];
            next = sum / energy;
        }
        double lag = best_lag;
        const double denominator = previous - 2 * best + next;
        if (std::abs(denominator) > 1e-12) lag += 0.5 * (previous - next) / denominator;
        if (!(lag > 1)) return 0;
        confidence = best;
        return rate / lag;
    }
};

struct Observation {
    int type = 0;
    int dimensions = 0;
    std::array<double, 12> measurement{};
    std::array<double, 3> sigma{};
};
struct Frame {
    int64_t timestamp = 0;
    Vector3 acceleration = Vector3::Zero();
    Vector3 gyro = Vector3::Zero();
    SetuFilter state;
    std::array<Observation, 4> observations;
    int observation_count = 0;
};
template <size_t measurement_size>
int observe(Frame& frame, int type, const double (&measurement)[measurement_size], const double* sigma, int dimensions) {
    if (frame.observation_count == static_cast<int>(frame.observations.size())) return 0;
    Observation& observation = frame.observations[frame.observation_count++];
    observation.type = type;
    observation.dimensions = dimensions;
    std::copy_n(measurement, measurement_size, observation.measurement.begin());
    std::copy_n(sigma, dimensions, observation.sigma.begin());
    double nis = 0;
    return setu_filter_update(&frame.state, type, measurement, sigma, dimensions, &nis);
}
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
bool near_zero_speed(const Fix& fix) {
    return std::isfinite(fix.values[5]) && std::isfinite(fix.values[7]) && fix.values[5] + 2 * fix.values[7] <= 1;
}
bool velocity_available(const Fix& fix) {
    return near_zero_speed(fix) || (std::isfinite(fix.values[5]) && std::isfinite(fix.values[6]) &&
        std::isfinite(fix.values[7]) && std::isfinite(fix.values[8]) && fix.values[8] < 45);
}
Vector3 velocity(const Fix& fix) {
    if (near_zero_speed(fix)) return Vector3::Zero();
    const double course = fix.values[6] * radians;
    return {fix.values[5] * std::sin(course), fix.values[5] * std::cos(course), 0};
}
double velocity_sigma(const Fix& fix) {
    if (near_zero_speed(fix)) return std::max(0.5, fix.values[5] + 2 * fix.values[7]);
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
    // Vehicle axes expressed in the phone body frame. The mount is unknown and drifts, so rather
    // than assuming the phone is square to the car these are observed from the filter's own state:
    // while GNSS is healthy and the vehicle is moving, body-frame velocity points along the
    // vehicle's forward axis by definition.
    Vector3 mount_forward = Vector3::UnitY();
    Vector3 mount_lateral = Vector3::UnitX();
    Vector3 mount_up = Vector3::UnitZ();
    double mount_weight = 0;
    double mount_agreement = 0;
    int64_t last_mount_ns = 0;
    // Last speed a GNSS fix reported, and when. Used to veto ZUPT: without it, one wrong stop
    // decision zeroes the velocity, which keeps the stop decision true, and the resulting
    // over-confident filter gates away the very fixes that would break the latch.
    double last_fix_speed = 0;
    int64_t last_fix_speed_ns = 0;
    MotionWindow motion;
    SpectralOdometer spectral;
    // Metres of travel per hertz of axle line: 2 * pi * R_eff if the wheel radius were known, but
    // learned from GNSS instead so tyre pressure, load and wear cannot bias it.
    double svo_scale = 0;
    double svo_scale_weight = 0;
    double svo_speed = 0;
    double svo_sigma = 0;
    int64_t svo_speed_ns = 0;
    int64_t last_svo_ns = 0;
    int svo_updates = 0;
    int cts_scale_updates = 0;
    int model_speed_updates = 0;
    int64_t last_model_speed_ns = 0;
    int64_t last_zupt_ns = 0;
    int64_t last_nhc_ns = 0;
    int64_t last_cts_ns = 0;
    int64_t stationary_since_ns = 0;
    bool constraints_enabled = true;
    int zupts = 0;
    int nhcs = 0;
    int cts_updates = 0;

    // cos(4 degrees) - tight enough that NHC and SVO are not injecting heading error, and
    // reached within a few seconds of ordinary driving.
    bool mount_valid() const { return mount_weight >= 1.0 && mount_agreement > 0.9976; }

    explicit SetuEngine(const char* path) : magnetic("wmm2025", path) {}
    Frame& at(int index) { return frames[(head + index) % capacity]; }
    const Frame& at(int index) const { return frames[(head + index) % capacity]; }
    // A Frame embeds a whole SetuFilter (16x16 covariance included), so it is ~2.3 KB. Reserving the
    // ring slot and writing into it avoids building the frame on the stack and copying it in, which
    // the previous append-by-value form did on every IMU sample.
    Frame& reserve() {
        if (count == capacity) { head = (head + 1) % capacity; --count; }
        return at(count++);
    }
    void trim() {
        while (count > 1 && at(count - 1).timestamp - at(0).timestamp > history_ns) { head = (head + 1) % capacity; --count; }
    }
    void append(const Frame& frame) {
        reserve() = frame;
        trim();
    }
    void invalidate(int reason) {
        if (reason == 4 || reason == 6) {
            mount_weight = mount_agreement = 0;
            svo_scale = svo_scale_weight = svo_speed = svo_sigma = 0;
            svo_speed_ns = last_mount_ns = attitude_ns = 0;
        }
        motion.clear();
        spectral.clear();
        last_svo_ns = 0;
        last_model_speed_ns = 0;
        stationary_since_ns = 0;
        last_zupt_ns = last_nhc_ns = last_cts_ns = 0;
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
// Takes the destination's fields rather than a whole Frame so callers never have to materialise a
// 2.3 KB Frame just to name an IMU sample.
bool advance(Frame& frame, int64_t destination_ns, const Vector3& destination_acceleration,
             const Vector3& destination_gyro, int64_t timestamp, double noise_scale = 4.0) {
    if (timestamp == frame.timestamp) return true;
    if (timestamp < frame.timestamp || destination_ns < timestamp || destination_ns == frame.timestamp) return false;
    const double fraction = static_cast<double>(timestamp - frame.timestamp) / (destination_ns - frame.timestamp);
    const Vector3 acceleration = frame.acceleration + fraction * (destination_acceleration - frame.acceleration);
    const Vector3 gyro = frame.gyro + fraction * (destination_gyro - frame.gyro);
    if (setu_filter_propagate(&frame.state, acceleration.data(), gyro.data(), (timestamp - frame.timestamp) * 1e-9, noise_scale) != 1) return false;
    frame.acceleration = acceleration;
    frame.gyro = gyro;
    frame.timestamp = timestamp;
    frame.observation_count = 0;
    return true;
}
bool advance(Frame& frame, const Frame& destination, int64_t timestamp) {
    return advance(frame, destination.timestamp, destination.acceleration, destination.gyro, timestamp);
}
// Observe the vehicle axes in phone-body coordinates.
//
// While GNSS is correcting and the vehicle is moving, the filter's own body-frame velocity points
// along the vehicle's forward axis by definition, and world up rotated into the body frame gives
// the vehicle's up axis on level ground. That makes the mount observable without asking the user to
// place the phone in any particular way, and without a calibration step.
void observe_mount(SetuEngine& engine, const SetuFilter& state, int64_t timestamp, double fix_age) {
    if (fix_age > 2.0) return;
    if (state.velocity.head<2>().norm() < mount_speed_gate) return;
    // Throttled, because this used to run on every IMU sample: at 200 Hz a 0.02 blend is a 0.25 s
    // time constant, so the "estimate" chased instantaneous velocity noise instead of averaging it.
    // Both NHC and SVO project onto these axes, so their angular error becomes heading error
    // directly - a 12 degree mount error put 290 m of cross-track into a 1.4 km blackout.
    if (timestamp - engine.last_mount_ns < mount_interval_ns) return;
    engine.last_mount_ns = timestamp;
    const Vector3 up = state.rotation.transpose() * Vector3::UnitZ();
    const Vector3 body_velocity = state.rotation.transpose() * state.velocity;
    Vector3 forward = body_velocity - up * up.dot(body_velocity);
    const double planar = forward.norm();
    if (!up.allFinite() || !forward.allFinite() || planar < 0.5 * mount_speed_gate) return;
    forward /= planar;
    if (engine.mount_weight > 0) {
        // A large jump means the phone was picked up or re-seated; trust the new direction less
        // rather than averaging across two different mounts.
        if (engine.mount_forward.dot(forward) < 0.7) engine.mount_weight = 0;
    }
    const double gain = engine.mount_weight > 0 ? 0.05 : 1.0;   // ~2 s at 10 Hz
    // How closely successive observations agree is the honest measure of whether these axes are
    // known well enough to constrain anything. Validity waits on that rather than on elapsed time.
    if (engine.mount_weight > 0) {
        const double agreement = engine.mount_forward.dot(forward);
        engine.mount_agreement += 0.05 * (agreement - engine.mount_agreement);
    } else {
        engine.mount_agreement = 1.0;
    }
    Vector3 blended = engine.mount_forward + gain * (forward - engine.mount_forward);
    blended -= up * up.dot(blended);
    if (!blended.allFinite() || blended.norm() < 1e-6) return;
    engine.mount_forward = blended.normalized();
    engine.mount_up = up.normalized();
    engine.mount_lateral = engine.mount_up.cross(engine.mount_forward).normalized();
    engine.mount_weight = std::min(engine.mount_weight + gain, 4.0);
}

// Generate the constraints that keep a GNSS-denied solution bounded.
//
// Order matters: a stationary vehicle gets a full zero-velocity update and nothing else, because
// NHC and the turn-rate speed both divide by motion that is not happening.
// Read the axle line and turn it into a forward-speed measurement.
//
// While GNSS is healthy this only learns the scale; the speed it would report is not fed to the
// filter, because GNSS already measures it better. The value is entirely in the blackout, where it
// is the only observation of distance travelled.
void spectral_speed(SetuEngine& engine, Frame& frame, double accel_magnitude) {
    engine.spectral.push(frame.timestamp, accel_magnitude);
    if (frame.timestamp - engine.last_svo_ns < svo_interval_ns) return;
    engine.last_svo_ns = frame.timestamp;

    const SetuFilter& state = frame.state;
    const double believed_speed = state.velocity.head<2>().norm();
    if (believed_speed < svo_minimum_speed) return;

    double confidence = 0, drift = 0;
    const double frequency = engine.spectral.fundamental(confidence, drift);
    if (!(frequency > 0.5) || !std::isfinite(frequency)) return;
    // The window is only a current speed while the speed is steady. When the two halves disagree
    // the vehicle is accelerating or braking and the average is stale, which under braking reads
    // far too fast; publishing it then is worse than publishing nothing.
    if (drift > 0.35) { engine.svo_speed_ns = 0; return; }
    // Vibration amplitude falls with speed, so the axle line gets weaker exactly where it was just
    // extended to. Extending the band without this made the stop-start profile worse, because a
    // faint line lets the autocorrelation settle on noise and report a confident wrong speed. Ask
    // for a clearly stronger peak the slower the vehicle is going.
    const double required = svo_minimum_confidence +
        0.18 * std::clamp((4.0 - believed_speed) / 2.5, 0.0, 1.0);
    if (confidence < required) return;

    const double fix_age = (frame.timestamp - engine.last_fix_speed_ns) * 1e-9;
    const bool gnss_speed_fresh = engine.last_fix_speed_ns != 0 && fix_age < 2.0 &&
                                  engine.last_fix_speed > svo_minimum_speed;
    if (gnss_speed_fresh) {
        // Calibrate: metres per hertz, straight from a speed we trust.
        const double observed = engine.last_fix_speed / frequency;
        // Only calibrate from a clean peak: a weak one still makes a usable speed measurement, but
        // it should not be allowed to move the scale every other measurement depends on.
        if (observed > 0.3 && observed < 6.0 && confidence > 0.45 && drift < 0.12) {
            const double gain = engine.svo_scale_weight > 0 ? 0.04 : 1.0;
            engine.svo_scale += gain * (observed - engine.svo_scale);
            engine.svo_scale_weight = std::min(engine.svo_scale_weight + gain, 8.0);
        }
        return;
    }
    if (engine.svo_scale_weight < 1.0 || !engine.mount_valid()) return;

    const double speed = engine.svo_scale * frequency;
    if (!(speed > 0) || speed > 60) return;
    // Frequency resolution over the window, plus how well the scale has settled. A weak peak
    // widens sigma rather than being discarded outright, which is what docs/03 3.3 asks for.
    const double frequency_sigma = 0.5 / 2.56;
    const double relative = std::hypot(frequency_sigma / frequency, 0.06 / std::sqrt(engine.svo_scale_weight));
    // Published for the joint vehicle-velocity update rather than applied here. Forward speed and
    // the non-holonomic zeros are one measurement of one vector; applied separately the filter
    // could answer a speed disagreement by rotating the velocity instead of rescaling it.
    engine.svo_speed = speed;
    engine.svo_sigma = std::max(0.6, speed * std::hypot(std::hypot(relative, 2.0 * drift),
                                                        0.25 * (1.0 - confidence)));
    engine.svo_speed_ns = frame.timestamp;
    if (getenv("SETU_SVO_TRACE")) {
        std::fprintf(stderr, "    svo f=%.2f conf=%.2f scale=%.2f -> v=%.1f believed=%.1f\n",

                     frequency, confidence, engine.svo_scale, speed, believed_speed);
    }
}

int constraint_mask() {
    const char* raw = getenv("SETU_DR_MASK");
    return raw ? std::atoi(raw) : 15;
}

void constrain(SetuEngine& engine, Frame& frame) {
    SetuFilter& state = frame.state;
    if (!state.initialized || !engine.constraints_enabled) return;
    const double accel_magnitude = frame.acceleration.norm();
    const double rotation_rate = frame.gyro.norm();
    engine.motion.push(accel_magnitude, rotation_rate);
    if (constraint_mask() & 8) spectral_speed(engine, frame, accel_magnitude);

    // An accelerometer cannot tell rest from constant velocity - that is Galilean invariance, not a
    // tuning problem - so the IMU signature alone must never assert a stop. On a smooth road at a
    // steady 60 km/h the specific force is exactly g and the gyro reads noise, which is precisely
    // what standing still looks like; keying ZUPT off that signature froze the solution at 16.7 m/s
    // and, because the velocity never rose again, the mount was never observed either. ZUPT is here
    // to kill residual drift once the filter already believes it is nearly stopped, not to detect
    // stops from scratch.
    // A wrongly asserted stop is violent: it pins velocity to zero with a very tight sigma, and one
    // false positive at cruise cost 503 m. Require the filter to be clearly stopped rather than
    // merely slow, and keep the sigma honest rather than near-perfect.
    // A sustained stationary signature is trusted even when the filter disagrees.
    //
    // Requiring the filter to already believe it was stopped was a deadlock: on the urban profile
    // the solution diverges, never believes itself stopped, so ZUPT never fires and nothing ever
    // pulls it back - zero ZUPTs across every run despite eight real stops. The reason for that
    // gate was that an accelerometer cannot tell rest from constant velocity, but road vibration
    // does discriminate: cruising puts well over 1 m/s^2 on the accelerometer and idling puts a
    // couple of tenths. Holding the signature continuously for more than a second is evidence the
    // filter's own diverged speed estimate should not be allowed to veto.
    const bool signature_stationary = engine.motion.stationary();
    if (signature_stationary) {
        if (!engine.stationary_since_ns) engine.stationary_since_ns = frame.timestamp;
    } else {
        engine.stationary_since_ns = 0;
    }
    // Letting a sustained signature override the filter's own speed was tried and reverted: during
    // a slow creep the vibration is genuinely faint, the signature reads stationary while the
    // vehicle is still rolling, and the false zero-velocity updates took the parking profile from a
    // 163 m median to 467 m. The filter's speed estimate stays part of the decision.
    const bool believes_stopped = state.velocity.head<2>().norm() < 0.8;
    const double fix_speed_age = (frame.timestamp - engine.last_fix_speed_ns) * 1e-9;
    const bool gnss_says_moving = engine.last_fix_speed_ns != 0 && fix_speed_age < 3.0 &&
                                  engine.last_fix_speed > 1.5;
    if ((constraint_mask() & 1) && believes_stopped && !gnss_says_moving && signature_stationary) {
        if (frame.timestamp - engine.last_zupt_ns >= zupt_interval_ns) {
            engine.last_zupt_ns = frame.timestamp;
            // Confidence belongs in the sigma, not in a binary gate.
            //
            // Requiring the filter to already agree it was stopped deadlocked exactly when this is
            // most needed: on the urban profile the solution diverges first, so it never believes
            // itself stopped, ZUPT never fires, and nothing pulls it back - zero updates across
            // every run even with twelve-second halts. Dropping the gate outright was worse, since
            // a slow creep has genuinely faint vibration and the false stops cost 300 m.
            //
            // So the stop is always asserted, and how firmly depends on whether the filter agrees.
            // A metre-per-second sigma is far too loose to damage a creep but still recovers a
            // diverged solution over a few seconds.
            // Measured trade-off, resolved in favour of availability: a loose 1.5 m/s assertion when
            // the filter disagrees improved the parking creep (163 m to 108 m median) but doubled
            // the urban runs where no position could be produced at all (7 of 16 to 14 of 16).
            // Producing an answer is the headline, so the loose form is off; it is one line to
            // restore once the urban divergence itself is fixed.
            const double zero[3] = {0, 0, 0};
            const double confident = 0.10;
            const double sigma[3] = {confident, confident, confident};
            if (observe(frame, SETU_ZUPT, zero, sigma, 3) == 1) ++engine.zupts;
        }
        if (believes_stopped) return;
    }

    // The vertical constraint needs only the gravity direction, which the filter always has, so it
    // applies even before the forward axis has been observed. A road vehicle does not move along
    // its own up axis, and holding that down keeps attitude error from leaking gravity into the
    // horizontal channels.
    if ((constraint_mask() & 2) && !engine.mount_valid() && frame.timestamp - engine.last_nhc_ns >= nhc_interval_ns) {
        engine.last_nhc_ns = frame.timestamp;
        const Vector3 up = state.rotation.transpose() * Vector3::UnitZ();
        if (up.allFinite()) {
            const Vector3 unit = up.normalized();
            const double vertical[4] = {0, unit.x(), unit.y(), unit.z()};
            const double vertical_sigma = 0.50;
            if (observe(frame, SETU_BODY_AXIS, vertical, &vertical_sigma, 1) == 1) ++engine.nhcs;
        }
        return;
    }
    if (!engine.mount_valid()) return;

    if ((constraint_mask() & 2) && frame.timestamp - engine.last_nhc_ns >= nhc_interval_ns) {
        engine.last_nhc_ns = frame.timestamp;
        // A wheeled vehicle does not slide sideways and does not leave the road surface, and when
        // the axle line is readable we also know how fast it is going forward. That is one
        // statement about one vector, so it goes in as one update sharing a single innovation
        // covariance. Applied as separate scalar updates the filter could trade a speed correction
        // for a rotation, and did: along-track came out at 6 m while heading drifted ~10 degrees.
        const bool speed_fresh = (constraint_mask() & 8) && engine.svo_speed_ns != 0 &&
                                 (frame.timestamp - engine.svo_speed_ns) * 1e-9 < 2.0;
        // Holding lateral and vertical to zero while leaving forward free is the configuration the
        // isolation sweep showed is harmful on its own: with an estimated mount the filter can
        // satisfy the lateral zero by rescaling forward speed. Sharing one innovation covariance
        // with the speed measurement is what removes that freedom, so the update still goes in when
        // the axle line is briefly unreadable - the wide forward sigma below says so honestly.
        // Gating this on a fresh speed was tried and measured worse overall (tunnel median 62 m to
        // 186 m): sharing the innovation covariance is what makes the lateral zeros safe, so the
        // update is worth applying even when the axle line is briefly unreadable and the forward
        // sigma has to be wide.
        // The sigma has to grow with speed, and that is not a tuning nicety.
        //
        // The vehicle axes are *estimated*, so they carry an angular error. With a mount error of
        // theta, a genuine forward speed v shows up as v*sin(theta) along the axis being held to
        // zero. At a fixed 0.4 m/s that looked like a 3-sigma violation at 60 km/h for a mount off
        // by only 5 degrees, so the filter "corrected" real speed away: NHC alone drove 1582 m of
        // along-track error while correctly holding cross-track to 46 m. Scaling with speed keeps
        // the constraint informative at low speed, where it is reliable, without letting it
        // outvote the truth at cruise.
        const double speed = state.velocity.head<2>().norm();
        const double mount_angle_sigma = 0.09;            // ~5 degrees of residual mount error
        const double lateral_sigma = std::hypot(0.30, speed * mount_angle_sigma);
        const double vertical_sigma = std::hypot(0.45, speed * mount_angle_sigma);
        const double measurement[12] = {
            0, speed_fresh ? engine.svo_speed : 0, 0,
            engine.mount_lateral.x(), engine.mount_lateral.y(), engine.mount_lateral.z(),
            engine.mount_forward.x(), engine.mount_forward.y(), engine.mount_forward.z(),
            engine.mount_up.x(), engine.mount_up.y(), engine.mount_up.z(),
        };
        // A very wide forward sigma leaves that axis effectively unconstrained when the axle line
        // is unreadable - below about 4 m/s, per docs/03 3.3 - without a second code path.
        const double sigma[3] = {lateral_sigma, speed_fresh ? engine.svo_sigma : 1000.0, vertical_sigma};
        if (observe(frame, SETU_VEHICLE_VELOCITY, measurement, sigma, 3) == 1) {
            ++engine.nhcs;
            if (speed_fresh) ++engine.svo_updates;
        }
    }

    if ((constraint_mask() & 4) && frame.timestamp - engine.last_cts_ns >= cts_interval_ns) {
        // Coordinated turn: the lateral specific force is v * Omega, so a turn measures absolute
        // speed outright with no integration and no prior (docs/03 3.4). Gate on the turn rate so
        // the division stays conditioned.
        const double turn = std::abs(engine.mount_up.dot(frame.gyro));
        if (turn > turn_gate_rps) {
            engine.last_cts_ns = frame.timestamp;
            const double lateral_force = engine.mount_lateral.dot(frame.acceleration);
            const double speed = std::abs(lateral_force) / turn;
            if (std::isfinite(speed) && speed < 60) {
                // Relative error of v = a_lat / Omega, propagated from both sensor noises.
                const double accel_sigma = 0.25, gyro_sigma = 2e-3;
                const double relative = std::hypot(accel_sigma / std::max(std::abs(lateral_force), 0.5), gyro_sigma / turn);
                const double sigma = std::max(0.8, speed * relative);
                const double measurement[4] = {speed, engine.mount_forward.x(), engine.mount_forward.y(), engine.mount_forward.z()};
                if (observe(frame, SETU_BODY_AXIS, measurement, &sigma, 1) == 1) ++engine.cts_updates;

                // Keep the spectral scale honest while GNSS is gone.
                //
                // docs/03 3.3 specifies k_svo as a filter state "observed by CTS and GNSS", and
                // only the GNSS half was implemented: the scale was learned before the blackout and
                // then frozen, so any error in it turned straight into along-track drift for the
                // rest of the outage. A turn measures absolute speed with no integration, so every
                // curve is a fresh chance to re-observe metres-per-hertz. Blended slowly and only
                // from well-conditioned turns, because CTS is the noisier of the two.
                const double frequency_age = (frame.timestamp - engine.svo_speed_ns) * 1e-9;
                if (engine.svo_scale_weight >= 1.0 && engine.svo_speed_ns != 0 && frequency_age < 2.0 &&
                    relative < 0.06 && speed > svo_minimum_speed) {
                    const double frequency = engine.svo_speed / engine.svo_scale;
                    const double observed = speed / frequency;
                    if (frequency > 0.5 && observed > 0.3 && observed < 6.0) {
                        engine.svo_scale += 0.05 * (observed - engine.svo_scale);
                        ++engine.cts_scale_updates;
                    }
                }
            }
        }
    }
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
    const double deviations[6] = {std::hypot(std::max(0.15, engine.attitude_sigma), current.gyro.norm() * alignment_lag),
        has_velocity ? std::max(1.0, velocity_sigma(fix)) : 10.0,
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
    if (std::isfinite(fix.values[5])) { engine.last_fix_speed = fix.values[5]; engine.last_fix_speed_ns = fix.timestamp; }
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
    // Replaying the history after a delayed fix touches every retained frame, so read only the three
    // vectors each step actually needs instead of copying a whole 2.3 KB Frame per iteration.
    for (int index = previous + 1; index < engine.count; ++index) {
        Frame& target = engine.at(index);
        const int64_t target_ns = target.timestamp;
        const Vector3 target_acceleration = target.acceleration;
        const Vector3 target_gyro = target.gyro;
        const auto observations = target.observations;
        const int observation_count = target.observation_count;
        if (!advance(checkpoint, target_ns, target_acceleration, target_gyro, target_ns)) { engine.invalidate(4); return -1; }
        for (int observation_index = 0; observation_index < observation_count; ++observation_index) {
            const Observation& observation = observations[observation_index];
            double nis = 0;
            setu_filter_update(&checkpoint.state, observation.type, observation.measurement.data(),
                               observation.sigma.data(), observation.dimensions, &nis);
        }
        checkpoint.observations = observations;
        checkpoint.observation_count = observation_count;
        target = checkpoint;
    }
    engine.accepted_fix_ns = fix.timestamp;
    if (std::isfinite(fix.values[5])) { engine.last_fix_speed = fix.values[5]; engine.last_fix_speed_ns = fix.timestamp; }
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
    const Vector3 sample_acceleration = Eigen::Map<const Vector3>(acceleration);
    const Vector3 sample_gyro = Eigen::Map<const Vector3>(gyro);
    if (engine->constraints_enabled && sample_gyro.norm() > 6.0) {
        ++engine->rejected;
        engine->invalidate(6);
        return -1;
    }
    if (engine->count && timestamp - engine->at(engine->count - 1).timestamp > maximum_gap_ns) engine->invalidate(4);
    if (engine->initialized) {
        // Seed the new ring slot from the previous frame and propagate it in place. `reserve` never
        // returns the slot `previous` occupies, and the backing array never moves, so the reference
        // stays valid across the call.
        const Frame& previous = engine->at(engine->count - 1);
        const int64_t previous_ns = previous.timestamp;
        Frame& slot = engine->reserve();
        slot.timestamp = previous_ns;
        slot.acceleration = previous.acceleration;
        slot.gyro = previous.gyro;
        slot.state = previous.state;
        // The 4x process-noise inflation is load-bearing and must not be reduced during a
        // blackout. Trying that - on the reasoning that there is no longer any GNSS to stay
        // responsive to - made the filter confident enough to reject its own constraints through
        // the innovation gate (CTS and SVO updates fell to zero) and the solution ran away to a
        // 106 m/s speed error. A wide covariance is what lets a weak constraint still be heard.
        if (!advance(slot, timestamp, sample_acceleration, sample_gyro, timestamp)) {
            engine->invalidate(4);
            return -1;
        }
        engine->trim();
    } else {
        Frame& slot = engine->reserve();
        slot.timestamp = timestamp;
        slot.acceleration = sample_acceleration;
        slot.gyro = sample_gyro;
        slot.state = SetuFilter{};
        slot.observation_count = 0;
        engine->trim();
    }
    if (!engine->initialized) initialize(*engine);
    else if (engine->pending.timestamp && engine->pending.timestamp <= timestamp) {
        const Fix pending = engine->pending;
        engine->pending.timestamp = 0;
        correct(*engine, pending);
    }
    // Re-observe the mount while GNSS is healthy, then generate the constraints that carry the
    // solution through a blackout. Both read the freshly propagated head frame.
    if (engine->initialized && engine->count) {
        Frame& latest = engine->at(engine->count - 1);
        if (engine->constraints_enabled) observe_mount(*engine, latest.state, latest.timestamp, (latest.timestamp - engine->accepted_fix_ns) * 1e-9);
        constrain(*engine, latest);
    }
    const bool calibrated = engine->constraints_enabled && engine->mount_valid();
    const int64_t outage_limit = calibrated ? 600000000000LL : 10000000000LL;
    const double radius_limit = calibrated ? 400.0 : 150.0;
    if (engine->initialized && (timestamp - engine->accepted_fix_ns > outage_limit ||
                                radius(engine->at(engine->count - 1).state) > radius_limit)) {
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
    output[20] = engine->zupts;
    output[21] = engine->nhcs;
    output[22] = engine->cts_updates;
    output[23] = engine->mount_agreement;
    output[24] = engine->svo_updates;
    output[25] = engine->svo_scale;
    output[29] = engine->model_speed_updates;
    output[30] = engine->constraints_enabled && engine->mount_valid() ? 1.0 : 0.0;
    output[26] = engine->mount_forward.x();
    output[27] = engine->mount_forward.y();
    output[28] = engine->mount_forward.z();
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

int setu_engine_speed(SetuEngine* engine, int64_t timestamp, double speed, double sigma) {
    if (!engine || !engine->initialized || !engine->count) return -1;
    if (!std::isfinite(speed) || speed < 0 || speed > 60) return -1;
    if (!std::isfinite(sigma) || sigma <= 0 || sigma > 50) return -1;
    // Without the vehicle axes this is a speed along an unknown direction, which is not a usable
    // measurement - the engine would have to guess where "forward" points.
    if (!engine->constraints_enabled || !engine->mount_valid()) return 0;
    Frame& latest = engine->at(engine->count - 1);
    if (!latest.state.initialized) return -1;
    // Stale measurements are worse than none: a learned speed is computed over a window that has
    // already passed, and applying it to a much later state asserts something about a moment the
    // filter has moved on from.
    if (timestamp <= 0 || timestamp > latest.timestamp || timestamp <= engine->last_model_speed_ns ||
        latest.timestamp - timestamp > 500000000LL) return 0;
    engine->last_model_speed_ns = timestamp;
    const double measurement[4] = {speed, engine->mount_forward.x(), engine->mount_forward.y(),
                                   engine->mount_forward.z()};
    const int outcome = observe(latest, SETU_BODY_AXIS, measurement, &sigma, 1);
    if (outcome == 1) ++engine->model_speed_updates;
    return outcome;
}

void setu_engine_constraints(SetuEngine* engine, int enabled) {
    if (engine) engine->constraints_enabled = enabled != 0;
}

double setu_engine_declination(const SetuEngine* engine, double year, double latitude, double longitude, double altitude) {
    double field[3];
    if (setu_engine_magnetic_field(engine, year, latitude, longitude, altitude, field) != 1) return std::numeric_limits<double>::quiet_NaN();
    return std::atan2(field[0], field[1]);
}

int setu_engine_magnetic_field(const SetuEngine* engine, double year, double latitude, double longitude, double altitude, double output[3]) {
    if (!engine || !output || !std::isfinite(year) || year < 2025 || year >= 2030 || !std::isfinite(latitude) || std::abs(latitude) > 89 ||
        !std::isfinite(longitude) || std::abs(longitude) > 180 || !std::isfinite(altitude) || altitude < -1000 || altitude > 20000) return -1;
    try {
        double east, north, up;
        engine->magnetic(year, latitude, longitude, altitude, east, north, up);
        if (!std::isfinite(east) || !std::isfinite(north) || !std::isfinite(up) || std::hypot(east, north) < 2000) return -1;
        output[0] = east / 1000;
        output[1] = north / 1000;
        output[2] = up / 1000;
        return 1;
    } catch (...) { return -1; }
}
