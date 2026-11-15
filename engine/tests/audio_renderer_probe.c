/* Run the production audio probe without game modules or an audio device.
 * Only the unrelated host IPC/event transport is replaced here. */
#include "../runtime/runtime.h"
#include "../runtime/ipc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Noreturn void runtime_fail(const char *why) { fprintf(stderr, "%s\n", why); exit(1); }
void *ipc_guest(uint64_t address, uint64_t size) { (void)size; return (void *)(uintptr_t)address; }
void dm_guest_write_prepare(void *address, size_t size) { (void)address; (void)size; }
uint32_t runtime_event_new(void) { static uint32_t next; return ++next; }
uint32_t runtime_event_readable(uint32_t event) { return event; }
void runtime_event_signal(uint32_t event) { (void)event; }
void hle_bind_system_event(void *event, int autoclear) { (void)event; (void)autoclear; }
void hle_signal_system_event(void *event) { (void)event; }
void runtime_ipc_register(const char *name, IpcHandler handler, IpcOpen open, void (*close)(void *)) {
    (void)name; (void)handler; (void)open; (void)close;
}
uint32_t runtime_ipc_new_session(const char *name, IpcHandler handler, void *state, void (*close)(void *)) {
    (void)name; (void)handler; (void)state; (void)close;
    runtime_fail("audio fixture must not open an IPC session");
}
void ipc_out(IpcResponse *response, const void *data, uint32_t size) {
    if (size > sizeof response->data - response->data_size) runtime_fail("fixture IPC output bounds");
    memcpy(response->data + response->data_size, data, size); response->data_size += size;
}
const void *ipc_arg(const IpcRequest *request, uint32_t offset, uint32_t size) {
    if (offset > request->data_size || size > request->data_size - offset) runtime_fail("fixture IPC input bounds");
    return request->data + offset;
}
_Noreturn void ipc_unimplemented(const IpcSession *session, const IpcRequest *request) {
    (void)session; (void)request; runtime_fail("unexpected fixture IPC call");
}

int main(void) {
    setenv("TOTK_AUDIO_OFF", "1", 1);
    unsetenv("TOTK_AUDIO_CAPTURE"); unsetenv("TOTK_AUDIO_DUMP"); unsetenv("TOTK_LIMITER_REFERENCE");
    runtime_audio_probe();
    return 0;
}
