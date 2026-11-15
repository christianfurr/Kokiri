"""CPU fixture checks that preview capture preferences cannot create external folders."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


class PreviewScreenshotTests(unittest.TestCase):
    def test_private_preview_refuses_folder_changes_before_writes(self):
        source = r'''
#include "screenshot.h"
static int saves, removes;
static char saved[PATH_MAX];
int runtime_setting_word(const char *name,char *word,size_t size) {
    (void)name;snprintf(word,size,"%s",saved);return saved[0]!=0;
}
void runtime_setting_save(const char *name,const char *word,const char *what) {
    (void)name;(void)what;saves++;snprintf(saved,sizeof saved,"%s",word);
}
void runtime_setting_remove(const char *name) { (void)name;removes++;saved[0]=0; }
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    const char *why=NULL;int problem=-1;uint64_t available=0;struct stat file;
    setenv("KOKIRI_HUMAN_PREVIEW_ROOT","/private/preview",1);
    if(screenshot_directory_set(argv[1],&why,&problem,&available) || !why || saves || removes ||
       !lstat(argv[1],&file) || errno!=ENOENT)return 3;
    if(screenshot_directory_set("",&why,&problem,&available) || saves || removes)return 4;
    unsetenv("KOKIRI_HUMAN_PREVIEW_ROOT");
    if(!screenshot_directory_set(argv[1],&why,&problem,&available) || saves!=1 || lstat(argv[1],&file))return 5;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            fixture = work / "fixture.c"
            fixture.write_text(source)
            binary = work / "fixture"
            subprocess.run(["xcrun", "clang", "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                            "-Wno-pointer-bool-conversion", "-DGAME_OOT=1", "-DGAME_NS2=1",
                            "-I", str(ENGINE / "runtime"), str(fixture), "-o", str(binary)],
                           check=True, timeout=20)
            subprocess.run([str(binary), str(work / "external")], check=True, timeout=5)
