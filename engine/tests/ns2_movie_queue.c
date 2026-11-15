/* Exercise the real nn::codec output queues without game files or a GPU. */
#define clock_gettime_nsec_np test_clock_ns
#include "../runtime/ns2_codec.c"
#include <assert.h>

static uint64_t virtual_ns;
uint64_t test_clock_ns(clockid_t which) { (void)which; return virtual_ns; }
_Noreturn void runtime_fail(const char *why) { fprintf(stderr, "%s\n", why); abort(); }
static void event_noop(void *event) { (void)event; }
void *runtime_symbol(const char *name) { (void)name; return (void *)event_noop; }
void hle_signal_system_event(void *event) { (void)event; }
void hle_bind_system_event(void *event, int autoclear) { (void)event; (void)autoclear; }
/* AV1 packet decoding is independently exercised by the actual game. These
   stubs are never reached: the queue receives synthetic owned I420 pictures. */
mav1 *mav1_new(void) { return (mav1 *)calloc(1, 1); }
void mav1_free(mav1 *a) { free(a); }
void mav1_reset(mav1 *a) { (void)a; }
const char *mav1_backend(const mav1 *a) { (void)a; return "test"; }
int mav1_decode(mav1 *a, const uint8_t *bytes, size_t n, mav1_picture *out) {
    (void)a; (void)bytes; (void)n; (void)out; abort();
}

static unsigned checks;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); exit(1); } checks++; } while (0)

static void queues_valid(const cv_dec *d) {
    unsigned owned[CV_BUFS] = {0}, pending[CV_BUFS] = {0};
    CHECK(d->fcount <= 8 && d->pcount <= CV_BUFS && d->nheld <= CV_HOLD);
    for (unsigned k = 0; k < d->fcount; k++) CHECK(!owned[d->fifo[(d->fhead + k) % 8]]++);
    for (unsigned k = 0; k < d->pcount; k++) {
        unsigned i = d->pend[(d->phead + k) % CV_BUFS];
        /* Acquire may hand out a pending buffer before its sync is ready. */
        CHECK(!pending[i]++ && !d->buf[i].filled && d->buf[i].reg);
    }
}

static void fixture(cv_dec *d, cv_pool *pool, unsigned count, int codec) {
    *d = (cv_dec){.magic = CV_MAGIC, .id = 1, .codec = codec};
    pthread_mutex_init(&d->mu, NULL);
    CHECK(!g_cv[d->id - 1]); g_cv[d->id - 1] = d;
    *pool = (cv_pool){.magic = CV_MAGIC, .count = count, .w = 2, .h = 2};
    pool->img = calloc(count, sizeof *pool->img);
    for (unsigned i = 0; i < count; i++) {
        d->buf[i] = (cv_buf){.pool = pool, .pidx = i, .reg = 1, .gen = 1};
        d->fifo[d->fcount++] = i;
        d->pend[d->pcount++] = i;
    }
}

static void cleanup(cv_dec *d, cv_pool *pool) {
    CHECK(g_cv[d->id - 1] == d); g_cv[d->id - 1] = NULL;
    for (unsigned i = 0; i < pool->count; i++) if (pool->img[i]) vpx_img_free(pool->img[i]);
    for (int i = 0; i < d->nheld; i++) vpx_img_free(d->held[i]);
    if (d->last_skipped) vpx_img_free(d->last_skipped);
    free(pool->img);
    if (d->av1) mav1_free(d->av1);
    else if (d->vpx_ok) CHECK(vpx_codec_destroy(&d->vpx) == VPX_CODEC_OK);
    pthread_mutex_destroy(&d->mu);
}

static int64_t consume(cv_dec *d, int *eos) {
    cv_dec *handle = d;
    uint32_t i; cv_sync sync;
    CHECK(cv_dec_acq(&i, &sync, &handle) == 0);
    CHECK(gs_try_wait(&sync));
    uint16_t w, h, cw, ch; int64_t ts; bool end;
    CHECK(cv_dec_props(&w, &h, &cw, &ch, &ts, &end, &handle, i) == 0);
    CHECK(sync.gen == d->buf[i].gen && sync.idx == i);
    *eos = end;
    cv_dec_rel(&handle, i, sync);
    queues_valid(d);
    return ts;
}

static Result properties(cv_dec *d, uint32_t index, int64_t *pts, bool *eos) {
    uint16_t w, h, cw, ch; cv_dec *handle = d;
    return cv_dec_props(&w, &h, &cw, &ch, pts, eos, &handle, index);
}

static void publish(cv_dec *d, int64_t pts, uint8_t value) {
    vpx_image_t *im = vpx_img_alloc(NULL, VPX_IMG_FMT_I420, 2, 2, 1);
    CHECK(im != NULL); memset(im->planes[0], value, 4);
    im->planes[1][0] = im->planes[2][0] = 128;
    CHECK(cv_hold(d, im, pts)); drain(d);
}

static void submit_eof(cv_dec *d) {
    cv_dec *handle = d; uint64_t submitted;
    CHECK(!cv_dec_submit(&submitted, &handle, NULL, 0, 0, true));
}

static void reset_ready(unsigned buffers, unsigned pictures, int codec) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, buffers, codec);
    cv_dec *handle = &d; virtual_ns = 0;
    for (unsigned i = 0; i < pictures; i++) publish(&d, i * 16666667ll, (uint8_t)(16 + i));
    submit_eof(&d);
    unsigned filled[CV_BUFS], generation[CV_BUFS]; vpx_image_t *images[CV_BUFS];
    for (unsigned i = 0; i < buffers; i++) {
        filled[i] = d.buf[i].filled; generation[i] = d.buf[i].gen; images[i] = pool.img[i];
    }
    CHECK(!cv_dec_reset(&handle));
    CHECK(!d.clock.started && !d.nheld && !d.last_skipped && !d.eos_pending);
    CHECK(d.fcount == buffers && d.pcount == buffers);
    for (unsigned i = 0; i < buffers; i++) {
        CHECK(!d.buf[i].filled && !d.buf[i].eos && !d.buf[i].ts);
        CHECK(d.buf[i].gen == generation[i] + filled[i]);
        CHECK(pool.img[i] == images[i]);
        CHECK(d.pend[(d.phead + i) % CV_BUFS] == i);
    }
    queues_valid(&d);
    uint32_t first; cv_sync sync;
    CHECK(!cv_dec_acq(&first, &sync, &handle) && first == 0);
    CHECK(!gs_try_wait(&sync));
    int64_t pts; bool end;
    CHECK(properties(&d, first, &pts, &end) == CV_NONE && !d.clock.started);
    virtual_ns = 5000000000ull;
    publish(&d, 9000000000ll, 90); submit_eof(&d);
    CHECK(gs_try_wait(&sync));
    CHECK(!properties(&d, first, &pts, &end) && !end && pts == 9000000000ll);
    CHECK(d.clock.started && d.clock.start_pts == pts && d.clock.start_ns == virtual_ns);
    CHECK(pool.img[first]->planes[0][0] == 90);
    cv_dec_rel(&handle, first, sync);
    int eos; consume(&d, &eos); CHECK(eos);
    cleanup(&d, &pool);
}

static void reset_client_owned(int codec) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, 8, codec);
    cv_dec *handle = &d; virtual_ns = 0;
    for (unsigned i = 0; i < 4; i++) publish(&d, i * 16666667ll, (uint8_t)(32 + i));
    uint32_t held; cv_sync sync; CHECK(!cv_dec_acq(&held, &sync, &handle) && held == 0);
    vpx_image_t *image = pool.img[held]; uint32_t generation = d.buf[held].gen;
    CHECK(!cv_dec_reset(&handle));
    CHECK(d.buf[held].filled && d.buf[held].gen == generation && gs_try_wait(&sync));
    CHECK(pool.img[held] == image && image->planes[0][0] == 32);
    int64_t pts; bool end;
    CHECK(!properties(&d, held, &pts, &end) && pts == 0 && !end);
    CHECK(!d.clock.started);
    CHECK(d.pcount == 7);
    for (unsigned i = 0; i < 7; i++) CHECK(d.pend[(d.phead + i) % CV_BUFS] == i + 1);
    virtual_ns = 6000000000ull;
    publish(&d, 12000000000ll, 91); submit_eof(&d);
    int eos; CHECK(consume(&d, &eos) == 12000000000ll && !eos);
    CHECK(d.clock.start_pts == 12000000000ll && d.clock.start_ns == virtual_ns);
    CHECK(!properties(&d, held, &pts, &end) && pts == 0 && !end);
    CHECK(d.clock.start_pts == 12000000000ll && pool.img[held] == image);
    cv_dec_rel(&handle, held, sync);
    consume(&d, &eos); CHECK(eos);
    cleanup(&d, &pool);
}

static void reset_pending_client(int codec) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, 8, codec);
    cv_dec *handle = &d; virtual_ns = 0;
    uint32_t held; cv_sync sync; CHECK(!cv_dec_acq(&held, &sync, &handle) && held == 0);
    CHECK(!gs_try_wait(&sync));
    CHECK(!cv_dec_reset(&handle));
    CHECK(d.buf[held].gen == sync.gen && d.pcount == 8 && d.fcount == 7);
    for (unsigned i = 0; i < 8; i++) CHECK(d.pend[(d.phead + i) % CV_BUFS] == i);
    queues_valid(&d);
    publish(&d, 7000000000ll, 92); submit_eof(&d);
    int64_t pts; bool end;
    CHECK(gs_try_wait(&sync));
    CHECK(!properties(&d, held, &pts, &end) && pts == 7000000000ll && !end);
    cv_dec_rel(&handle, held, sync);
    int eos; consume(&d, &eos); CHECK(eos);
    cleanup(&d, &pool);
}

static void reset_undelivered(void) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, 1, CV_AV1);
    cv_dec *handle = &d; virtual_ns = 0;
    publish(&d, 0, 16); ns2_movie_clock_start(&d.clock, virtual_ns, 0);
    virtual_ns = 1000000000ull;
    publish(&d, 16666667ll, 17); CHECK(d.last_skipped != NULL);
    publish(&d, 2000000000ll, 18); submit_eof(&d);
    CHECK(d.nheld == 1 && d.last_skipped && d.eos_pending);
    CHECK(!cv_dec_reset(&handle));
    CHECK(!d.nheld && !d.last_skipped && !d.eos_pending && !d.clock.started);
    publish(&d, 10000000000ll, 93); submit_eof(&d);
    int eos; CHECK(consume(&d, &eos) == 10000000000ll && !eos);
    consume(&d, &eos); CHECK(eos);
    cleanup(&d, &pool);
}

static void reset_unreleased(int codec) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, 8, codec);
    cv_dec *handle = &d;
    /* Register initially exposes an empty buffer; only Release makes it writable. */
    d.pcount = 0;
    for (unsigned i = 0; i < 8; i++) d.buf[i].gen = 0;
    CHECK(!cv_dec_reset(&handle)); CHECK(!d.pcount && d.fcount == 8);
    for (unsigned i = 0; i < 8; i++) CHECK(!d.buf[i].gen && !d.buf[i].filled);
    cleanup(&d, &pool);
}

static void simulate(int fps, int hitch, int enabled, unsigned buffers) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, buffers, CV_AV1);
    const int total = 180;
    int produced = 0, ended = 0, saw_eos = 0, displayed = 0;
    int64_t last_pts = -1, max_lag = 0;
    uint64_t next_render = 0;
    for (virtual_ns = 0; virtual_ns <= 8000000000ull; virtual_ns += 1000000) {
        while (produced < total && (uint64_t)produced * 1000000000ull / 60 <= virtual_ns && d.nheld < CV_HOLD) {
            vpx_image_t *im = vpx_img_alloc(NULL, VPX_IMG_FMT_I420, 2, 2, 1);
            CHECK(im != NULL);
            cv_hold(&d, im, (int64_t)produced++ * 1000000000ll / 60);
            drain(&d);
        }
        if (produced == total && !ended) { d.eos_pending = 1; drain(&d); ended = 1; }
        if (virtual_ns < next_render || (hitch && virtual_ns >= 1000000000ull && virtual_ns < 1750000000ull)) continue;
        next_render = virtual_ns + 1000000000ull / (unsigned)fps;
        if (!d.fcount || !d.buf[d.fifo[d.fhead]].filled) continue;
        int eos = 0; int64_t pts = consume(&d, &eos);
        if (eos) { saw_eos = 1; break; }
        CHECK(pts > last_pts); last_pts = pts; displayed++;
        int64_t lag = (int64_t)virtual_ns - pts;
        if (lag > max_lag) max_lag = lag;
        // The first render after a forced hitch may need one producer refill.
        if (enabled && (!hitch || virtual_ns < 1000000000ull || virtual_ns > 1850000000ull))
            CHECK(lag >= -1000000 && lag <= 70000000);
    }
    CHECK(saw_eos && produced == total && displayed > 0);
    CHECK(last_pts == (int64_t)(total - 1) * 1000000000ll / 60);
    if (enabled && fps < 60) CHECK(d.dropped > 0);
    if (!enabled && fps == 30) CHECK(max_lag > 1000000000 && !d.dropped);
    printf("buffers=%u fps=%d hitch=%d sync=%d displayed=%d dropped=%llu max_lag_ms=%.3f\n",
           buffers, fps, hitch, enabled, displayed, (unsigned long long)d.dropped, max_lag / 1e6);
    cleanup(&d, &pool);
}

static void ownership_and_reset(void) {
    cv_dec d; cv_pool pool; fixture(&d, &pool, 8, CV_AV1);
    cv_dec *handle = &d;
    for (int i = 0; i < 8; i++) {
        cv_hold(&d, vpx_img_alloc(NULL, VPX_IMG_FMT_I420, 2, 2, 1), i * 16666667ll);
        drain(&d);
    }
    virtual_ns = 1000000000ull;
    uint32_t held; cv_sync sync; CHECK(!cv_dec_acq(&held, &sync, &handle));
    ns2_movie_clock_start(&d.clock, virtual_ns, 0);
    virtual_ns += 1000000000;
    uint32_t other; cv_sync other_sync; CHECK(!cv_dec_acq(&other, &other_sync, &handle));
    CHECK(held != other && d.buf[held].filled && d.buf[held].gen == sync.gen);
    CHECK(d.dropped == 6);
    cv_dec_rel(&handle, held, sync); cv_dec_rel(&handle, other, other_sync);
    queues_valid(&d);
    CHECK(!cv_dec_reset(&handle)); CHECK(!d.clock.started && !d.dropped);
    cleanup(&d, &pool);
    Ns2MovieClock c = {0}; ns2_movie_clock_start(&c, 100, -100);
    CHECK(ns2_movie_clock_target(&c, 90) == -100);
    CHECK(ns2_movie_clock_target(&c, 200) == 0);
    c = (Ns2MovieClock){0, INT64_MAX - 2, 1}; CHECK(ns2_movie_clock_target(&c, 10) == INT64_MAX);
    c = (Ns2MovieClock){0, 0, 1}; CHECK(ns2_movie_clock_target(&c, UINT64_MAX) == INT64_MAX);
}

int main(int argc, char **argv) {
    int enabled = argc < 2 || strcmp(argv[1], "off");
    setenv("OOT_MOVIE_SYNC", enabled ? "1" : "0", 1);
    for (unsigned buffers = 1; buffers <= 8; buffers += 7) {
        simulate(30, 0, enabled, buffers);
        if (enabled) {
            simulate(24, 0, 1, buffers); simulate(60, 0, 1, buffers);
            simulate(120, 0, 1, buffers); simulate(30, 1, 1, buffers);
        }
    }
    if (enabled) {
        ownership_and_reset();
        reset_undelivered();
    }
    /* Stop/Flush share their output-state contract for every codec, including
       when AV1 presentation synchronization is disabled. */
    for (int codec = CV_VP8; codec <= CV_AV1; codec++) {
        reset_ready(1, 1, codec); reset_ready(8, 8, codec); reset_ready(8, 2, codec);
        reset_client_owned(codec); reset_pending_client(codec); reset_unreleased(codec);
        printf("reset codec=%s sync=%d\n", k_name[codec], enabled);
    }
    printf("{\"status\":\"pass\",\"checks\":%u,\"sync\":%s}\n", checks, enabled ? "true" : "false");
    return 0;
}
