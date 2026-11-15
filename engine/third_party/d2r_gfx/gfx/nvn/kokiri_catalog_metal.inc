/* Included after the actual shader options/parser/local-cache declarations.
 * This observes the selected device; it never creates another Metal device. */
#include "kokiri_catalog_runtime.h"
#include "kokiri_catalog_pso.h"
#include <mach-o/loader.h>
#include <uuid/uuid.h>
#include <dirent.h>
static pthread_mutex_t g_kcr_mutex = PTHREAD_MUTEX_INITIALIZER;
static NSDictionary *g_kcr_identity;
static NSString *g_kcr_output;
static NSString *g_kcr_rows;
static _Atomic int g_kcr_invalid;
static int g_kcr_receipt_revoked;
static kcr_generation g_kcr_generation;
static NSString *const kcr_list_name = @"kokiri-catalog://verified-local-candidate";

static int kokiri_catalog_invalidate(void) {
    int ok = 1;
    pthread_mutex_lock(&g_kcr_mutex);
    if (g_kcr_identity) {
        atomic_store(&g_kcr_invalid, 1);
        NSMutableDictionary *invalid = [g_kcr_identity mutableCopy];
        invalid[@"valid"] = @NO; invalid[@"reason"] = @"runtime-options-changed";
        if (g_kcr_output && !g_kcr_receipt_revoked) {
            ok = kcr_invalidate_receipt(g_kcr_output, kcr_json(invalid));
            if (ok) g_kcr_receipt_revoked = 1;
        }
    }
    pthread_mutex_unlock(&g_kcr_mutex);
    return ok;
}
static int kokiri_catalog_flag_enter(void) {
    kcr_change_begin(&g_kcr_generation);
    int ok = kokiri_catalog_invalidate();
    if (!ok) MLOG("[kokiri-catalog] setting deferred: the owned compatibility receipt could not be revoked");
    return ok;
}
static void kokiri_catalog_flag_leave(int *guard) { (void)guard; kcr_change_end(&g_kcr_generation); }
static NSString *kcr_build_string(const char *name) {
    char value[128] = {0}; size_t n = sizeof value;
    return !sysctlbyname(name, value, &n, NULL, 0) && n && n < sizeof value ? @(value) : nil;
}
static NSString *kcr_metal_uuid(void) {
    /* Public Metal API image's in-memory LC_UUID, not a per-device registry ID
     * and not a claimed readable/private compiler-service executable digest. */
    Dl_info image = {0};
    if (!dladdr((const void *)&MTLCreateSystemDefaultDevice, &image) || !image.dli_fbase) return nil;
    const struct mach_header_64 *h = image.dli_fbase;
    if (h->magic != MH_MAGIC_64 || h->sizeofcmds > 1024 * 1024) return nil;
    const unsigned char *at = (const void *)(h + 1), *end = at + h->sizeofcmds;
    for (uint32_t i = 0; i < h->ncmds && at + sizeof(struct load_command) <= end; ++i) {
        const struct load_command *c = (const void *)at;
        if (c->cmdsize < sizeof *c || c->cmdsize > (size_t)(end - at)) return nil;
        if (c->cmd == LC_UUID && c->cmdsize == sizeof(struct uuid_command)) {
            uuid_string_t text; uuid_unparse_lower(((const struct uuid_command *)c)->uuid, text); return @(text);
        }
        at += c->cmdsize;
    }
    return nil;
}
static int kcr_effective(_Atomic int *value, const char *environment, int fallback) {
    int v = atomic_load_explicit(value, memory_order_relaxed);
    const char *e = getenv(environment); return v >= 0 ? v : e ? atoi(e) : fallback;
}
static NSDictionary *kcr_observe(void) {
#if TARGET_OS_IPHONE || defined(DEVICE_XLATE)
    return nil; /* The first adapter covers native macOS runtime Metal JIT. */
#else
    if (!g_dev || shader_device_libs() || oot_umul_diagnostic_on()) return nil;
    /* Normal desktop loading also prefers shader-libs/<MSL-SHA>.metallib.
     * Its offline compiler receipt is not yet part of this adapter: do not
     * mislabel a mixed/precompiled build as the observed runtime JIT. */
    NSString *prebuilt = exe_rel("shader-libs");
    DIR *libraries = prebuilt ? opendir(prebuilt.fileSystemRepresentation) : NULL;
    if (libraries) {
        struct dirent *entry; int populated = 0;
        while ((entry = readdir(libraries))) {
            if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) { populated = 1; break; }
        }
        closedir(libraries); if (populated) return nil;
    } else if (prebuilt && access(prebuilt.fileSystemRepresentation, F_OK) == 0) return nil;
    int translation = kcr_effective(&g_mesh_translation, "OOT_MESH_TRANSLATION", 0);
    if (translation != 0) return nil; /* External generated source needs its own complete identity. */
    NSString *os = kcr_build_string("kern.osversion"), *arch = kcr_build_string("hw.machine"), *metal = kcr_metal_uuid();
    if (!os || !arch || !metal) return nil;
    char executable[4096]; uint32_t length = sizeof executable;
    if (_NSGetExecutablePath(executable, &length)) return nil;
    NSString *runtime = kcr_file_sha(@(executable), 1024ull * 1024 * 1024);
    NSString *resources = NSBundle.mainBundle.resourcePath;
    NSDictionary *base = kcr_object(kcr_read([resources stringByAppendingPathComponent:@"KokiriCatalogContext.json"], 65536));
    const char *native = getenv("TOTK_NATIVE_DIR"), *override = getenv("TOTK_SHADER_XLATE");
    NSString *translator = override && *override ? @(override) : native ? [@(native) stringByAppendingPathComponent:@"shader-service/totk_xlate"] : nil;
    if (!runtime || ![kcr_file_sha(translator, 1024ull * 1024 * 1024) isEqual:base[@"translator_sha256"]] ||
        ![base[@"shader_chain"] isEqual:@DMSH_CHAIN]) return nil;
    MTLCompileOptions *o = totk_precise_opts();
    if (o.libraries.count || o.preprocessorMacros.count || o.libraryType != MTLLibraryTypeExecutable || o.installName.length) return nil;
    NSMutableArray *families = [NSMutableArray array];
    const MTLGPUFamily known[] = {MTLGPUFamilyApple1, MTLGPUFamilyApple2, MTLGPUFamilyApple3,
        MTLGPUFamilyApple4, MTLGPUFamilyApple5, MTLGPUFamilyApple6, MTLGPUFamilyApple7,
        MTLGPUFamilyApple8, MTLGPUFamilyApple9, MTLGPUFamilyMac1, MTLGPUFamilyMac2,
        MTLGPUFamilyCommon1, MTLGPUFamilyCommon2, MTLGPUFamilyCommon3, MTLGPUFamilyMetal3};
    for (NSUInteger i = 0; i < sizeof known / sizeof known[0]; ++i) if ([g_dev supportsFamily:known[i]]) [families addObject:@(known[i])];
    NSDictionary *compiler = @{@"schema":@"kokiri-compiler-identity/1", @"observed":@YES,
        @"kind":@"metal-runtime-jit", @"platform_compiler_identity":@"os-build-and-public-metal-api-image",
        @"os_build":os, @"metal_api_uuid":metal};
    NSDictionary *target = @{@"schema":@"kokiri-target-identity/1", @"observed":@YES,
        @"architecture":arch, @"device_model":g_dev.name, @"families":families,
        @"unified_memory":@(g_dev.hasUnifiedMemory), @"low_power":@(g_dev.isLowPower),
        @"removable":@(g_dev.isRemovable), @"os_build":os, @"metal_api_uuid":metal};
    NSMutableDictionary *options = [@{@"schema":@"kokiri-options-identity/1", @"observed":@YES,
        @"runtime_sha256":runtime, @"translator_sha256":base[@"translator_sha256"], @"shader_chain":@DMSH_CHAIN,
        @"language_version":@(o.languageVersion), @"preserve_invariance":@(o.preserveInvariance),
        @"library_type":@(o.libraryType), @"optimization_level":@(o.optimizationLevel),
        @"macros":@{}, @"dynamic_libraries":@[],
        @"translator_debug_mode":@(getenv("TOTK_SHADER_DEBUGMODE") ? atoi(getenv("TOTK_SHADER_DEBUGMODE")) : 1),
        @"mesh_pack":@(kcr_effective(&g_mesh_pack, "OOT_MESH_PACK_VARYINGS", 1) != 0),
        @"mesh_translation":@(translation),
        @"mesh_empty_export":@(kcr_effective(&g_mesh_empty_export, "OOT_MESH_EMPTY_EXPORT", 0) != 0)} mutableCopy];
    if (@available(macOS 15.0, *)) { options[@"math_mode"] = @(o.mathMode); options[@"math_functions"] = @(o.mathFloatingPointFunctions); }
    else options[@"fast_math"] = @(o.fastMathEnabled);
    if ([o respondsToSelector:@selector(enableLogging)]) options[@"enable_logging"] = @(o.enableLogging);
    NSMutableDictionary *identity = [kcr_identity(base, runtime, compiler, target, options) mutableCopy];
    if (identity) identity[@"local_variant_directory"] = totk_rt_dir();
    return identity;
#endif
}
static int kcr_local_variant(NSString *name, int stage, NSDictionary *proof, uint64_t *budget) {
    if (stage == -1) {
        return kcr_render_proof(name, proof);
    }
    if (!g_warm_scope || !totk_shader_scope_contains(g_warm_scope, name)) return 0;
    NSString *source = totk_rt_file([name stringByAppendingString:@".metal"]);
    NSString *reflection = totk_rt_file([name stringByAppendingString:@".json"]);
    return kcr_local_shader(source, reflection, name, stage, @DMSH_CHAIN, proof, budget);
}
static NSString *kokiri_catalog_begin(void) {
    const char *output = getenv("KOKIRI_CATALOG_IDENTITY_FILE");
    const char *candidate = getenv("KOKIRI_CATALOG_HANDOFF"), *digest = getenv("KOKIRI_CATALOG_HANDOFF_SHA256");
    if (!(output && *output) && !(candidate && *candidate)) return nil;
    uint64_t generation = 0;
    NSDictionary *identity = kcr_snapshot(&g_kcr_generation, &generation) ? kcr_observe() : nil;
    pthread_mutex_lock(&g_kcr_mutex);
    if (!kcr_snapshot_unchanged(&g_kcr_generation, generation)) identity = nil;
    g_kcr_output = output && *output ? @(output) : nil; g_kcr_identity = identity;
    if (atomic_load(&g_kcr_invalid)) identity = nil;
    if (g_kcr_output) (void)kcr_write(g_kcr_output, kcr_json(identity ?: @{@"schema":@"kokiri-runtime-identity/1", @"valid":@NO, @"reason":@"unqualified-runtime-options"}));
    pthread_mutex_unlock(&g_kcr_mutex);
    if (!identity || !(candidate && *candidate && digest && *digest)) return nil;
    NSUInteger admitted = 0;
    __block uint64_t budget = 64ull * 1024 * 1024;
    g_kcr_rows = kcr_handoff(kcr_read(@(candidate), KCR_MAX_BYTES), @(digest), identity,
        ^int(NSString *name, int stage, NSDictionary *proof) { @autoreleasepool { return kcr_local_variant(name, stage, proof, &budget); } }, &admitted);
    MLOG("[kokiri-catalog] admitted=%lu bounded-local-pipeline-recipes=%s", (unsigned long)admitted, g_kcr_rows ? "yes" : "no");
    return g_kcr_rows ? kcr_list_name : nil;
}
static NSString *kokiri_warm_text(NSString *path) {
    if ([path isEqual:kcr_list_name]) return atomic_load(&g_kcr_invalid) ? nil : g_kcr_rows;
    return [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
}
