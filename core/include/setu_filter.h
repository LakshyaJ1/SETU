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
    SETU_VELOCITY_2D = 8
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
