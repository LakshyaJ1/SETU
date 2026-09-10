#include "setu_filter.h"
#include "setu_engine.h"
#include <jni.h>
#include <cstdint>

namespace {
SetuFilter* filter(jlong handle) { return reinterpret_cast<SetuFilter*>(static_cast<intptr_t>(handle)); }

bool read(JNIEnv* environment, jdoubleArray source, double* target, int length) {
    if (!source || environment->GetArrayLength(source) != length) return false;
    environment->GetDoubleArrayRegion(source, 0, length, target);
    return !environment->ExceptionCheck();
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativeCreate(JNIEnv*, jobject) {
    return reinterpret_cast<intptr_t>(setu_filter_create());
}

extern "C" JNIEXPORT void JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativeDestroy(JNIEnv*, jobject, jlong handle) {
    setu_filter_destroy(filter(handle));
}

extern "C" JNIEXPORT jint JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativeReset(JNIEnv* environment, jobject, jlong handle,
    jdoubleArray rotation, jdoubleArray position, jdoubleArray velocity, jdoubleArray deviations, jdouble scale) {
    double attitude[9], location[3], speed[3], uncertainty[6];
    if (!read(environment, rotation, attitude, 9) || !read(environment, position, location, 3)
        || !read(environment, velocity, speed, 3) || !read(environment, deviations, uncertainty, 6)) return -1;
    return setu_filter_reset(filter(handle), attitude, location, speed, uncertainty, scale);
}

extern "C" JNIEXPORT jint JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativePropagate(JNIEnv* environment, jobject, jlong handle,
    jdoubleArray acceleration, jdoubleArray angular_rate, jdouble seconds, jdouble noise_scale) {
    double accel[3], gyro[3];
    if (!read(environment, acceleration, accel, 3) || !read(environment, angular_rate, gyro, 3)) return -1;
    return setu_filter_propagate(filter(handle), accel, gyro, seconds, noise_scale);
}

extern "C" JNIEXPORT jdoubleArray JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativeUpdate(JNIEnv* environment, jobject, jlong handle,
    jint kind, jdoubleArray measurement, jdoubleArray deviations) {
    if (!measurement) return nullptr;
    const int dimension = environment->GetArrayLength(measurement);
    if (dimension < 1 || dimension > 3) return nullptr;
    double values[3], uncertainty[3], nis;
    if (!read(environment, measurement, values, dimension) || !read(environment, deviations, uncertainty, dimension)) return nullptr;
    const int status = setu_filter_update(filter(handle), kind, values, uncertainty, dimension, &nis);
    const double result[2] = {static_cast<double>(status), nis};
    jdoubleArray output = environment->NewDoubleArray(2);
    if (output) environment->SetDoubleArrayRegion(output, 0, 2, result);
    return output;
}

extern "C" JNIEXPORT jdoubleArray JNICALL
Java_com_setu_navigator_estimation_NativeFilter_nativeSnapshot(JNIEnv* environment, jobject, jlong handle) {
    double state[SETU_SNAPSHOT_SIZE];
    if (setu_filter_snapshot(filter(handle), state) != 1) return nullptr;
    jdoubleArray output = environment->NewDoubleArray(SETU_SNAPSHOT_SIZE);
    if (output) environment->SetDoubleArrayRegion(output, 0, SETU_SNAPSHOT_SIZE, state);
    return output;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeCreate(JNIEnv* environment, jobject, jstring directory) {
    if (!directory) return 0;
    const char* path = environment->GetStringUTFChars(directory, nullptr);
    if (!path) return 0;
    SetuEngine* engine = setu_engine_create(path);
    environment->ReleaseStringUTFChars(directory, path);
    return reinterpret_cast<jlong>(engine);
}

extern "C" JNIEXPORT void JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeDestroy(JNIEnv*, jobject, jlong handle) {
    setu_engine_destroy(reinterpret_cast<SetuEngine*>(handle));
}

extern "C" JNIEXPORT jint JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeImu(JNIEnv* environment, jobject, jlong handle, jlong timestamp,
    jdoubleArray acceleration, jdoubleArray angular_rate) {
    double accel[3], gyro[3];
    if (!read(environment, acceleration, accel, 3) || !read(environment, angular_rate, gyro, 3)) return -1;
    return setu_engine_imu(reinterpret_cast<SetuEngine*>(handle), timestamp, accel, gyro);
}

extern "C" JNIEXPORT jint JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeAttitude(JNIEnv* environment, jobject, jlong handle,
    jlong timestamp, jdoubleArray rotation, jdouble sigma) {
    double matrix[9];
    if (!read(environment, rotation, matrix, 9)) return -1;
    return setu_engine_attitude(reinterpret_cast<SetuEngine*>(handle), timestamp, matrix, sigma);
}

extern "C" JNIEXPORT jint JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeGnss(JNIEnv* environment, jobject, jlong handle,
    jlong timestamp, jdoubleArray observation) {
    double values[10];
    if (!read(environment, observation, values, 10)) return -1;
    return setu_engine_gnss(reinterpret_cast<SetuEngine*>(handle), timestamp, values);
}

extern "C" JNIEXPORT jdoubleArray JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativePoll(JNIEnv* environment, jobject, jlong handle) {
    double values[SETU_ESTIMATE_SIZE];
    if (setu_engine_poll(reinterpret_cast<SetuEngine*>(handle), values) < 0) return nullptr;
    jdoubleArray output = environment->NewDoubleArray(SETU_ESTIMATE_SIZE);
    if (output) environment->SetDoubleArrayRegion(output, 0, SETU_ESTIMATE_SIZE, values);
    return output;
}

extern "C" JNIEXPORT jdouble JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeDeclination(JNIEnv*, jobject, jlong handle,
    jdouble year, jdouble latitude, jdouble longitude, jdouble altitude) {
    return setu_engine_declination(reinterpret_cast<SetuEngine*>(handle), year, latitude, longitude, altitude);
}

extern "C" JNIEXPORT jdoubleArray JNICALL
Java_com_setu_navigator_estimation_NativeEngine_nativeMagneticField(JNIEnv* environment, jobject, jlong handle,
    jdouble year, jdouble latitude, jdouble longitude, jdouble altitude) {
    double values[3];
    if (setu_engine_magnetic_field(reinterpret_cast<SetuEngine*>(handle), year, latitude, longitude, altitude, values) != 1) return nullptr;
    jdoubleArray output = environment->NewDoubleArray(3);
    if (output) environment->SetDoubleArrayRegion(output, 0, 3, values);
    return output;
}
