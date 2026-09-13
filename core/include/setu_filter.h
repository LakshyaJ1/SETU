#ifndef SETU_FILTER_H
#define SETU_FILTER_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SetuFilter SetuFilter;

enum SetuMeasurement {
    SETU_POSITION = 0,
    SETU_VELOCITY = 1,
    SETU_FORWARD_SPEED = 2,
    SETU_NHC = 3,
    SETU_ZUPT = 4,
    SETU_SVO_FREQUENCY = 5,
    SETU_POSITION_2D = 6,
    SETU_ALTITUDE = 7,
    SETU_VELOCITY_2D = 8,
    /*
     * Velocity along one arbitrary unit axis of the body frame.
     *
     * measurement = { target_speed, axis_x, axis_y, axis_z }, dimension = 1.
     *
     * SETU_NHC and SETU_ZUPT constrain the body axes themselves, which is only correct when the
     * phone is mounted square to the vehicle. The mount is unknown and drifts, so the engine
     * estimates the vehicle axes in phone-body coordinates and constrains those instead; this kind
     * is what lets it do that without a second filter frame.
     */
    SETU_BODY_AXIS = 9,
    /*
     * The whole vehicle-frame velocity in one update.
     *
     * measurement = { target_lateral, target_forward, target_up,
     *                 lateral_axis[3], forward_axis[3], up_axis[3] }, dimension = 3,
     * where the axes are unit vectors in the phone body frame.
     *
     * Applying the non-holonomic constraints and the spectral speed as three separate scalar
     * updates is not the same thing when the states are correlated: the filter could satisfy a
     * disagreement about forward speed by rotating the velocity rather than rescaling it, which
     * turned a 1 % speed bias into degrees of heading error. Sharing one innovation covariance
     * removes that trade.
     */
    SETU_VEHICLE_VELOCITY = 10
};

enum { SETU_SNAPSHOT_SIZE = 279 };

SetuFilter* setu_filter_create(void);
void setu_filter_destroy(SetuFilter* filter);
int setu_filter_reset(SetuFilter* filter, const double rotation[9],
                      const double position[3], const double velocity[3],
                      const double standard_deviations[6], double scale);
int setu_filter_propagate(SetuFilter* filter, const double acceleration[3],
                          const double angular_rate[3], double seconds, double noise_scale);
int setu_filter_update(SetuFilter* filter, int kind, const double* measurement,
                       const double* standard_deviations, int dimension, double* nis);
int setu_filter_snapshot(const SetuFilter* filter, double output[SETU_SNAPSHOT_SIZE]);

#ifdef __cplusplus
}
#endif
#endif
