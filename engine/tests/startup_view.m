/* Offscreen AppKit fixture: no game, Metal device, window, or synthetic timing. */
#import "kokiri_startup.h"
#include <stdio.h>

static unsigned checks;
static void require(BOOL condition, const char *reason) {
    checks++;
    if (!condition) { fprintf(stderr, "FAILED: %s\n", reason); exit(2); }
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        require(argc == 3, "logo and optional image output paths supplied");
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        const struct { uint64_t frames; int warming, released, visible; } readiness[] = {
            {0,0,0,0}, {0,0,1,0}, {0,1,0,0}, {0,1,1,0},
            {1,0,0,1}, {1,0,1,1}, {1,1,0,0}, {1,1,1,1}
        };
        for (unsigned i = 0; i < sizeof readiness / sizeof *readiness; i++)
            require(kokiri_startup_can_reveal(readiness[i].frames, readiness[i].warming, readiness[i].released) ==
                    readiness[i].visible, "first frame and warm release gate");
        NSURL *logo = [NSURL fileURLWithPath:@(argv[1])];
        KokiriStartupView *view = [[KokiriStartupView alloc] initWithFrame:NSMakeRect(0,0,1280,720) logoURL:logo];
        require(view.progress.indeterminate, "unknown startup work is indeterminate");
        require(!view.hidden, "startup initially visible");
        require([view hitTest:NSMakePoint(100,100)] == nil, "artwork does not capture input");
        NSImageView *mark = (NSImageView *)view.subviews.firstObject;
        require(mark.image != nil && mark.image.size.width > 0, "actual original logo loads");
        NSTextField *title = (NSTextField *)view.subviews[1];
        NSParagraphStyle *paragraph = [title.attributedStringValue attribute:NSParagraphStyleAttributeName atIndex:0 effectiveRange:NULL];
        require(paragraph.alignment == NSTextAlignmentCenter, "wordmark centers beneath the logo");
        NSSize sizes[] = {{1280,720}, {1920,1080}, {320,180}, {640,360}, {320,420}, {1280,720}};
        for (unsigned i = 0; i < sizeof sizes / sizeof *sizes; i++) {
            view.frame = NSMakeRect(0,0,sizes[i].width,sizes[i].height);
            [view layoutSubtreeIfNeeded]; [view layout];
            for (NSView *child in view.subviews)
                if (!child.hidden) require(NSContainsRect(view.bounds, child.frame), "visible content fits supported viewport");
        }
        view.stage.stringValue = @"Verifying game data";
        view.detail.stringValue = @"Visual fixture · synthetic phase data";
        view.progress.indeterminate = NO;
        view.progress.doubleValue = 42;
        require(view.progress.doubleValue == 42, "supplied progress displayed without generated advancement");
        [view.progress stopAnimation:nil];
        NSBitmapImageRep *bitmap = [view bitmapImageRepForCachingDisplayInRect:view.bounds];
        require(bitmap != nil, "offscreen bitmap available");
        [view cacheDisplayInRect:view.bounds toBitmapImageRep:bitmap];
        require([bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}]
            && [[bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@(argv[2]) atomically:YES],
            "actual view rendered to PNG");
        printf("Kokiri startup view: %u checks PASS\n", checks);
    }
    return 0;
}
