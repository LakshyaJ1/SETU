cmake_minimum_required(VERSION 3.22)
project(setu_core LANGUAGES CXX)

include(FetchContent)

# Build settings applied to the estimator targets below.
#
# The measured situation on NDK r28 + AGP: the Debug variant compiles at -O2 (from Gradle's
# `cppFlags`), not -O0, because the NDK toolchain sets CMAKE_CXX_FLAGS_DEBUG to
# `-fno-limit-debug-info` rather than `-O0`. What it does *not* define is NDEBUG, so every Eigen
# expression in the debug APK - the one actually being demonstrated - runs with Eigen's internal
# assertions live. That is a real cost in a filter that propagates a 16x16 covariance per IMU sample.
#
# These are attached per target rather than through CMAKE_CXX_FLAGS_<CONFIG>, because the NDK
# toolchain file sets those as ordinary variables which shadow any cache entry written here. Target
# options are emitted after the directory flags, so -O3 reliably wins over the inherited -O2.
function(setu_configure_numerics target)
    target_compile_options(${target} PRIVATE
        -O3
        # REQ-N8 wants bit-identical replay, so contraction and fast-math relaxations are forbidden.
        -ffp-contract=off
        -fno-fast-math)
    target_compile_definitions(${target} PRIVATE NDEBUG EIGEN_NO_DEBUG)
endfunction()
FetchContent_Declare(eigen
    URL https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz
    URL_HASH SHA256=8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72)
FetchContent_GetProperties(eigen)
if(NOT eigen_POPULATED)
    FetchContent_Populate(eigen)
endif()

FetchContent_Declare(geographiclib
    URL https://codeload.github.com/geographiclib/geographiclib/tar.gz/refs/tags/v2.5
    URL_HASH SHA256=347319e3dc5dd2d58116ff1ecb8c0ae11c9f095c655fe289992b3208bc7a32fc)
FetchContent_GetProperties(geographiclib)
if(NOT geographiclib_POPULATED)
    FetchContent_Populate(geographiclib)
endif()
set(PROJECT_VERSION 2.5)
set(PROJECT_VERSION_MAJOR 2)
set(PROJECT_VERSION_MINOR 5)
set(PROJECT_VERSION_PATCH 0)
set(GEOGRAPHICLIB_HAVE_LONG_DOUBLE 1)
set(GEOGRAPHICLIB_WORDS_BIGENDIAN 0)
set(GEOGRAPHICLIB_PRECISION 2)
set(GEOGRAPHICLIB_LIB_TYPE_VAL 0)
configure_file(${geographiclib_SOURCE_DIR}/include/GeographicLib/Config.h.in
    ${CMAKE_CURRENT_BINARY_DIR}/GeographicLib/Config.h @ONLY)
add_library(setu_geodesy STATIC
    ${geographiclib_SOURCE_DIR}/src/Math.cpp
    ${geographiclib_SOURCE_DIR}/src/Geocentric.cpp
    ${geographiclib_SOURCE_DIR}/src/LocalCartesian.cpp
    ${geographiclib_SOURCE_DIR}/src/MagneticModel.cpp
    ${geographiclib_SOURCE_DIR}/src/MagneticCircle.cpp
    ${geographiclib_SOURCE_DIR}/src/SphericalEngine.cpp
    ${geographiclib_SOURCE_DIR}/src/CircularEngine.cpp
    ${geographiclib_SOURCE_DIR}/src/Utility.cpp)
target_include_directories(setu_geodesy PUBLIC ${geographiclib_SOURCE_DIR}/include ${CMAKE_CURRENT_BINARY_DIR})
set_target_properties(setu_geodesy PROPERTIES POSITION_INDEPENDENT_CODE ON)
setu_configure_numerics(setu_geodesy)

add_library(setu_core STATIC src/setu_filter.cpp src/setu_engine.cpp)
target_link_libraries(setu_core PUBLIC setu_geodesy)
target_compile_features(setu_core PUBLIC cxx_std_20)
target_include_directories(setu_core PUBLIC include PRIVATE ${eigen_SOURCE_DIR})
target_compile_definitions(setu_core PRIVATE EIGEN_MPL2_ONLY)
set_target_properties(setu_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
setu_configure_numerics(setu_core)

# GNSS-denied dead-reckoning benchmark. Built only on request, and built for the device rather than
# the host: it is the shipping arm64 code path that the requirement numbers have to hold for.
# See core/test/README.md for how to build and run it.
option(SETU_BUILD_TESTS "Build the native benchmarks" OFF)
if(SETU_BUILD_TESTS)
    add_executable(setu_dr_bench test/dr_bench.cpp)
    target_link_libraries(setu_dr_bench PRIVATE setu_core)
    target_include_directories(setu_dr_bench PRIVATE ${eigen_SOURCE_DIR})
    setu_configure_numerics(setu_dr_bench)
endif()
