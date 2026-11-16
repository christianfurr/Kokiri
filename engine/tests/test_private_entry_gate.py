"""Actual launcher gate with inert private handlers; no app or game launches."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ENGINE = Path(__file__).resolve().parents[1]


def function(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class PrivateEntryGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        root = Path(cls.work.name)
        cls.binary = root / "fixture"
        launcher = (ENGINE / "app/launcher.m").read_text()
        header = (ENGINE / "app/kokiri_development.h").read_text()
        start = launcher.index("int runtime_app_launch(")
        end = launcher.index("        NSString *root =", start)
        gate = launcher[start:end]
        numbers = "\n".join(function(header, name) for name in
                            ("static BOOL kokiri_dev_number(", "static BOOL kokiri_dev_schema("))
        source = root / "fixture.m"
        source.write_text(r'''
#import <Foundation/Foundation.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static NSDictionary *fixture_info;
@interface FixtureBundle:NSObject
+(instancetype)mainBundle;
-(NSDictionary *)infoDictionary;
@end
@implementation FixtureBundle
+(instancetype)mainBundle { return [FixtureBundle new]; }
-(NSDictionary *)infoDictionary { return fixture_info; }
@end
static int kokiri_human_preview_launch(int argc,char **argv,char ***boot) {
    (void)argv;(void)boot;return argc==3 ? 11 : 1;
}
static int kokiri_development_launch(int argc,char **argv,char ***boot) {
    (void)argv;(void)boot;return argc==3 ? 12 : 1;
}
''' + numbers + '\n#define NSBundle FixtureBundle\n' + gate + r'''
        if(check)return 13; /* The following real package check is read-only. */
        return 30; /* Shared player path: must never be reached by a marked app. */
    }
}
#undef NSBundle
int main(int argc,char **argv) { @autoreleasepool {
    if(argc<2)return 2;
    NSString *marker=@(argv[1]);id value=nil;
    if([marker isEqual:@"valid"])value=@1;
    else if([marker isEqual:@"boolean"])value=@YES;
    else if([marker isEqual:@"wrong"])value=@2;
    else if([marker isEqual:@"string"])value=@"1";
    else if([marker isEqual:@"null"])value=NSNull.null;
    fixture_info=value ? @{@"KokiriHumanPreviewVersion":value} : @{};
    char **boot=NULL;printf("%d\n",runtime_app_launch(argc-1,argv+1,&boot));
    return 0;
} }
''')
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        str(source), "-framework", "Foundation", "-o", str(cls.binary)],
                       check=True, timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def route(self, marker, *arguments):
        result = subprocess.run([str(self.binary), marker, *arguments], check=True,
                                capture_output=True, text=True, timeout=5)
        return int(result.stdout.strip())

    def test_marked_app_accepts_both_explicit_private_entries(self):
        self.assertEqual(self.route("valid", "--kokiri-preview", "/private/human"), 11)
        self.assertEqual(self.route("valid", "--kokiri-development", "/private/dev"), 12)

    def test_marked_app_never_reaches_shared_defaults(self):
        for arguments in ((), ("--unknown",), ("boot",), ("--check", "extra")):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.route("valid", *arguments), 1)
        self.assertEqual(self.route("valid", "--check"), 13)

    def test_invalid_marker_never_authorizes_a_private_or_shared_entry(self):
        for marker in ("boolean", "wrong", "string", "null"):
            for arguments in ((), ("--kokiri-preview", "/private/human"),
                              ("--kokiri-development", "/private/dev"), ("--check",)):
                with self.subTest(marker=marker, arguments=arguments):
                    self.assertEqual(self.route(marker, *arguments), 1)

    def test_unmarked_product_and_private_arity_behavior_are_preserved(self):
        self.assertEqual(self.route("none"), 30)
        self.assertEqual(self.route("none", "--kokiri-development", "/private/dev"), 12)
        self.assertEqual(self.route("none", "--kokiri-preview", "/private/human"), 1)
        for flag in ("--kokiri-preview", "--kokiri-development"):
            for arguments in ((flag,), (flag, "/private/root", "extra")):
                with self.subTest(arguments=arguments):
                    self.assertEqual(self.route("valid", *arguments), 1)
