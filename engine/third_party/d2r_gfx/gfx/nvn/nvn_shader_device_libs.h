/* Internal value semantics shared by the cached runtime getter and its CPU fixture. */
#pragma once
#include <string.h>

static int nvn_shader_device_libs_enabled(const char *value) {
    return value && !strcmp(value, "1");
}
