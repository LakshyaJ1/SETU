#ifndef SETU_ENGINE_H
#define SETU_ENGINE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct SetuEngine SetuEngine;
enum { SETU_ESTIMATE_SIZE = 20 };
SetuEngine* setu_engine_create(const char* magnetic_directory);
void setu_engine_destroy(SetuEngine* engine);
int setu_engine_attitude(SetuEngine* engine, int64_t timestamp_ns, const double rotation[9], double heading_sigma);
int setu_engine_imu(SetuEngine* engine, int64_t timestamp_ns, const double acceleration[3], const double angular_rate[3]);
int setu_engine_gnss(SetuEngine* engine, int64_t timestamp_ns, const double observation[10]);
int setu_engine_poll(const SetuEngine* engine, double output[SETU_ESTIMATE_SIZE]);
double setu_engine_declination(const SetuEngine* engine, double year, double latitude, double longitude, double altitude);
#ifdef __cplusplus
}
#endif
#endif
