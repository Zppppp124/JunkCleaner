/*
 * Minimal OpenCL stress prototype used to validate a self-contained
 * NVIDIA stress backend (no Python / no PyTorch required).
 *
 * Usage: ocl_stress_proto <seconds> <transient 0|1> <high_ms> <low_ms>
 * Output lines: "OK" / "BAD" / "CORRUPT:<reason>" / "DONE"
 */

#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#define SLEEP_MS(ms) Sleep((DWORD)(ms))
#else
#include <unistd.h>
#define SLEEP_MS(ms) usleep((useconds_t)((ms) * 1000))
#endif

static double now_sec(void) {
    return (double)clock() / (double)CLOCKS_PER_SEC;
}

static const char *KERNEL_SRC =
    "__kernel void heavy(__global float *a, __global float *b,"
    "                    const int n, const int iters) {\n"
    "    int row = get_global_id(0);\n"
    "    int col = get_global_id(1);\n"
    "    if (row >= n || col >= n) return;\n"
    "    float acc = 0.0f;\n"
    "    for (int k = 0; k < iters; ++k) {\n"
    "        float s = 0.0f;\n"
    "        for (int t = 0; t < 16; ++t) {\n"
    "            int idx = ((row + t) % n) * n + ((col + k + t) % n);\n"
    "            float v = a[idx] * b[idx];\n"
    "            s = fma(v, 1.000001f, s);\n"
    "        }\n"
    "        acc += s;\n"
    "    }\n"
    "    int out = row * n + col;\n"
    "    a[out] = acc;\n"
    "}\n";

static int check_finite(const float *buf, size_t count) {
    for (size_t i = 0; i < count; ++i) {
        float v = buf[i];
        if (!(v == v) || v > 1e30f || v < -1e30f) return 0;
    }
    return 1;
}

int main(int argc, char **argv) {
    double duration = argc > 1 ? atof(argv[1]) : 30.0;
    int transient = argc > 2 ? atoi(argv[2]) : 0;
    double high_ms = argc > 3 ? atof(argv[3]) : 120.0;
    double low_ms = argc > 4 ? atof(argv[4]) : 60.0;

    cl_platform_id platform = NULL;
    cl_uint num_platforms = 0;
    if (clGetPlatformIDs(1, &platform, &num_platforms) != CL_SUCCESS ||
        num_platforms == 0) {
        printf("ERROR: no OpenCL platform\n");
        return 2;
    }
    cl_device_id device = NULL;
    if (clGetDeviceIDs(platform, CL_DEVICE_TYPE_GPU, 1, &device, NULL)
            != CL_SUCCESS) {
        printf("ERROR: no OpenCL GPU device\n");
        return 2;
    }

    cl_int err = CL_SUCCESS;
    cl_context ctx = clCreateContext(NULL, 1, &device, NULL, NULL, &err);
    if (err != CL_SUCCESS) return 3;
    cl_command_queue queue = clCreateCommandQueue(ctx, device, 0, &err);
    if (err != CL_SUCCESS) return 3;

    cl_program program = clCreateProgramWithSource(
        ctx, 1, &KERNEL_SRC, NULL, &err);
    if (err != CL_SUCCESS) return 4;
    err = clBuildProgram(program, 1, &device, "-cl-fast-relaxed-math", NULL,
                         NULL);
    if (err != CL_SUCCESS) {
        size_t log_size = 0;
        clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, 0, NULL,
                              &log_size);
        char *log = (char *)malloc(log_size + 1);
        if (log) {
            clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG,
                                  log_size, log, NULL);
            log[log_size] = 0;
            printf("ERROR: build failed: %s\n", log);
            free(log);
        }
        return 4;
    }
    cl_kernel kernel = clCreateKernel(program, "heavy", &err);
    if (err != CL_SUCCESS) return 5;

    const int n = 2048;
    const size_t bytes = (size_t)n * (size_t)n * sizeof(float);
    float *host = (float *)malloc(bytes);
    if (!host) return 6;
    for (size_t i = 0; i < (size_t)n * n; ++i) {
        host[i] = (float)((i % 1000) * 0.001) + 0.1f;
    }

    cl_mem buf_a = clCreateBuffer(ctx, CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR,
                                  bytes, host, &err);
    cl_mem buf_b = clCreateBuffer(ctx, CL_MEM_READ_WRITE | CL_MEM_COPY_HOST_PTR,
                                  bytes, host, &err);
    if (err != CL_SUCCESS) return 6;

    const int iters = 64;
    clSetKernelArg(kernel, 0, sizeof(cl_mem), &buf_a);
    clSetKernelArg(kernel, 1, sizeof(cl_mem), &buf_b);
    clSetKernelArg(kernel, 2, sizeof(int), &n);
    clSetKernelArg(kernel, 3, sizeof(int), &iters);

    size_t global[2] = {(size_t)n, (size_t)n};
    double deadline = now_sec() + duration;
    int bad = 0;
    while (now_sec() < deadline) {
        double heavy_until = now_sec() + high_ms / 1000.0;
        while (now_sec() < heavy_until) {
            err = clEnqueueNDRangeKernel(queue, kernel, 2, NULL, global, NULL,
                                         0, NULL, NULL);
            if (err != CL_SUCCESS) {
                printf("CORRUPT:cl_error_%d\n", (int)err);
                bad = 1;
                break;
            }
        }
        if (bad) break;
        clFinish(queue);
        if (clEnqueueReadBuffer(queue, buf_a, CL_TRUE, 0, bytes, host, 0, NULL,
                                NULL) != CL_SUCCESS) {
            printf("CORRUPT:read_error\n");
            bad = 1;
            break;
        }
        if (!check_finite(host, (size_t)n * n)) {
            printf("CORRUPT:nonfinite\n");
            bad = 1;
            break;
        }
        if (transient) SLEEP_MS(low_ms);
    }

    printf(bad ? "BAD\n" : "OK\n");
    printf("DONE\n");
    clReleaseMemObject(buf_a);
    clReleaseMemObject(buf_b);
    clReleaseKernel(kernel);
    clReleaseProgram(program);
    clReleaseCommandQueue(queue);
    clReleaseContext(ctx);
    free(host);
    return bad ? 1 : 0;
}
