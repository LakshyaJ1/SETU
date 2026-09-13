#ifndef SETU_ENGINE_H
#define SETU_ENGINE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct SetuEngine SetuEngine;
/* 20..22 carry the dead-reckoning constraint counters (ZUPT, NHC, coordinated-turn
   speed) so callers can see the GNSS-denied path is actually engaging; 24..25 the
   spectral-odometer update count and its learned metres-per-hertz scale. */
enum { SETU_ESTIMATE_SIZE = 30 };
SetuEngine* setu_engine_create(const char* magnetic_directory);
void setu_engine_destroy(SetuEngine* engine);
int setu_engine_attitude(SetuEngine* engine, int64_t timestamp_ns, const double rotation[9], double heading_sigma);
int setu_engine_imu(SetuEngine* engine, int64_t timestamp_ns, const double acceleration[3], const double angular_rate[3]);
int setu_engine_gnss(SetuEngine* engine, int64_t timestamp_ns, const double observation[10]);
int setu_engine_poll(const SetuEngine* engine, double output[SETU_ESTIMATE_SIZE]);
/* Enable or disable the dead-reckoning constraints (ZUPT, NHC, coordinated-turn speed).
   On by default. Turning them off reproduces the GNSS-only behaviour, which is what the
   benchmark measures against. */
void setu_engine_constraints(SetuEngine* engine, int enabled);
/* Forward speed from an external estimator - the on-device learned model - applied along the
   vehicle axis the engine has worked out for itself. Returns 1 applied, 0 gated, -1 rejected.
   Speed is metres per second and sigma its one-sigma uncertainty; a caller that does not know its
   own uncertainty has nothing useful to contribute and should not call this. */
int setu_engine_speed(SetuEngine* engine, int64_t timestamp, double speed, double sigma);
double setu_engine_declination(const SetuEngine* engine, double year, double latitude, double longitude, double altitude);
int setu_engine_magnetic_field(const SetuEngine* engine, double year, double latitude, double longitude, double altitude, double output[3]);
#ifdef __cplusplus
}
#endif
#endif
