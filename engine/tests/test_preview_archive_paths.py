"""CPU-only archive-helper routing: no Metal, cache creation or cleanup."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


class PreviewArchivePathTests(unittest.TestCase):
    def test_claimed_private_entry_never_falls_back_to_shared_paths(self):
        source = r'''
#import <Foundation/Foundation.h>
#include <limits.h>
#include <stdio.h>
#define MLOG(...) fprintf(stderr,__VA_ARGS__)
#include "totk_pipeline_archive_folders.h"
static int ready;
int runtime_kokiri_development_active(void) { return 0; }
int runtime_kokiri_private_paths_ready(void) { return ready; }
int main(void) { @autoreleasepool {
    setenv("KOKIRI_HUMAN_PREVIEW_ROOT","/private/not-created-preview",1);
    if(par_ga_dirs().count)return 2;
    ready=1;NSArray *paths=par_ga_dirs();
    if(paths.count!=1 || ![paths[0][@"path"] isEqual:@"/private/not-created-preview/cache/archive-helper/com.apple.gpuarchiver"] ||
       ![paths[0][@"own"] boolValue])return 3;
    ready=0;if(par_ga_dirs().count)return 4;
    unsetenv("KOKIRI_HUMAN_PREVIEW_ROOT");setenv("KOKIRI_DEVELOPMENT_ROOT","/private/expired-development",1);
    if(par_ga_dirs().count)return 5;
    return 0;
} }
'''
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            fixture = work / "fixture.m"
            fixture.write_text(source)
            binary = work / "fixture"
            subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-function", "-Wno-pointer-bool-conversion",
                            "-I", str(ENGINE / "third_party/d2r_gfx/gfx/nvn"), str(fixture),
                            "-framework", "Foundation", "-o", str(binary)], check=True, timeout=20)
            subprocess.run([str(binary)], check=True, timeout=5)
