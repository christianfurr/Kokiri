/* Kokiri's native startup presentation. Status comes from the runtime's existing
   verification/import/warm-up callbacks; the artwork never invents progress. */
#pragma once
#import <Cocoa/Cocoa.h>
#include <math.h>
#include <stdint.h>

static inline int kokiri_startup_can_reveal(uint64_t frames, int warming, int title_released) {
    return frames > 0 && (!warming || title_released);
}

/* Keep AppKit's genuine indeterminate animation. Only the counted fill uses
   Kokiri's brass, without private tint APIs or an animation that advances work. */
@interface KokiriStartupProgress : NSProgressIndicator
@end
@implementation KokiriStartupProgress
-(void)setDoubleValue:(double)value { [super setDoubleValue:value]; [self setNeedsDisplay:YES]; }
-(void)setIndeterminate:(BOOL)value { [super setIndeterminate:value]; [self setNeedsDisplay:YES]; }
-(void)drawRect:(NSRect)dirtyRect {
    if (self.indeterminate) { [super drawRect:dirtyRect]; return; }
    NSRect track = NSInsetRect(self.bounds, 0, 1);
    CGFloat radius = NSHeight(track)/2;
    NSBezierPath *outline = [NSBezierPath bezierPathWithRoundedRect:track xRadius:radius yRadius:radius];
    [[NSColor colorWithCalibratedRed:0.32 green:0.41 blue:0.33 alpha:0.45] setFill];
    [outline fill];
    double range = self.maxValue-self.minValue;
    double fraction = range > 0 ? fmax(0, fmin(1, (self.doubleValue-self.minValue)/range)) : 0;
    if (fraction <= 0) return;
    NSRect fill = track; fill.size.width *= fraction;
    [NSGraphicsContext saveGraphicsState];
    [outline addClip];
    [[NSColor colorWithCalibratedRed:0.76 green:0.66 blue:0.39 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRoundedRect:fill xRadius:radius yRadius:radius] fill];
    [NSGraphicsContext restoreGraphicsState];
}
@end

@interface KokiriStartupView : NSView
@property(strong, readonly) NSTextField *stage;
@property(strong, readonly) NSTextField *detail;
@property(strong, readonly) NSProgressIndicator *progress;
-(instancetype)initWithFrame:(NSRect)frame logoURL:(NSURL *)logoURL;
@end

@implementation KokiriStartupView {
    NSImageView *_mark;
    NSTextField *_title;
    NSTextField *_subtitle;
    NSTextField *_footer;
}

static NSTextField *kokiri_startup_label(NSString *text, CGFloat size, NSFontWeight weight, NSColor *color) {
    NSTextField *label = [NSTextField labelWithString:text];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    label.textColor = color;
    label.alignment = NSTextAlignmentCenter;
    label.lineBreakMode = NSLineBreakByWordWrapping;
    label.maximumNumberOfLines = 2;
    return label;
}

-(instancetype)initWithFrame:(NSRect)frame logoURL:(NSURL *)logoURL {
    if (!(self = [super initWithFrame:frame])) return nil;
    self.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.wantsLayer = YES;
    self.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    NSColor *ivory = [NSColor colorWithCalibratedRed:0.96 green:0.95 blue:0.88 alpha:1];
    NSColor *muted = [NSColor colorWithCalibratedRed:0.66 green:0.75 blue:0.66 alpha:1];
    _mark = [[NSImageView alloc] initWithFrame:NSZeroRect];
    _mark.imageScaling = NSImageScaleProportionallyUpOrDown;
    _mark.image = logoURL ? [[NSImage alloc] initWithContentsOfURL:logoURL] : nil;
    [_mark setAccessibilityLabel:@"Kokiri leaf K logo"];
    [self addSubview:_mark];
    _title = kokiri_startup_label(@"KOKIRI", 30, NSFontWeightMedium, ivory);
    _subtitle = kokiri_startup_label(@"Ocarina of Time", 13, NSFontWeightRegular, muted);
    _stage = kokiri_startup_label(@"Starting the game", 17, NSFontWeightSemibold, ivory);
    _detail = kokiri_startup_label(@"Preparing the game environment", 12, NSFontWeightRegular, muted);
    _footer = kokiri_startup_label(@"NATIVE ON MAC", 9, NSFontWeightMedium,
        [NSColor colorWithCalibratedRed:0.69 green:0.63 blue:0.43 alpha:0.85]);
    for (NSView *view in @[_title, _subtitle, _stage, _detail, _footer]) [self addSubview:view];
    _progress = [[KokiriStartupProgress alloc] initWithFrame:NSZeroRect];
    _progress.style = NSProgressIndicatorStyleBar;
    _progress.controlSize = NSControlSizeSmall;
    _progress.minValue = 0;
    _progress.maxValue = 100;
    _progress.indeterminate = YES;
    [self addSubview:_progress];
    [self layout];
    return self;
}

-(BOOL)isOpaque { return YES; }
/* The startup artwork does not intercept normal window/menu input. */
-(NSView *)hitTest:(NSPoint)point { (void)point; return nil; }

-(void)layout {
    [super layout];
    CGFloat width = NSWidth(self.bounds), height = NSHeight(self.bounds);
    BOOL compact = height < 420;
    CGFloat contentWidth = fmax(1, fmin(480, width-32));
    CGFloat left = floor((width-contentWidth)/2);
    CGFloat center = NSMidY(self.bounds);
    CGFloat markSize = compact ? 44 : fmin(132, width*0.28);
    CGFloat cursor = center + (compact ? 76 : 175);
    _mark.frame = NSMakeRect(floor((width-markSize)/2), cursor-markSize, markSize, markSize);
    cursor -= markSize + (compact ? 4 : 16);
    CGFloat titleHeight = compact ? 24 : 44;
    _title.frame = NSMakeRect(left, cursor-titleHeight, contentWidth, titleHeight);
    NSMutableParagraphStyle *centered = [NSMutableParagraphStyle new];
    centered.alignment = NSTextAlignmentCenter;
    _title.attributedStringValue = [[NSAttributedString alloc] initWithString:@"KOKIRI" attributes:@{
        NSFontAttributeName:[NSFont systemFontOfSize:compact?20:30 weight:NSFontWeightMedium],
        NSForegroundColorAttributeName:_title.textColor, NSKernAttributeName:compact?@3:@6,
        NSParagraphStyleAttributeName:centered
    }];
    cursor -= titleHeight;
    _subtitle.hidden = compact;
    _footer.hidden = compact;
    if (!compact) {
        cursor -= 6;
        _subtitle.frame = NSMakeRect(left, cursor-18, contentWidth, 18);
        cursor -= 18+38;
    } else cursor -= 8;
    CGFloat stageHeight = compact ? 20 : 26;
    _stage.frame = NSMakeRect(left, cursor-stageHeight, contentWidth, stageHeight);
    cursor -= stageHeight + (compact ? 3 : 7);
    CGFloat detailHeight = compact ? 24 : 38;
    _detail.frame = NSMakeRect(left, cursor-detailHeight, contentWidth, detailHeight);
    cursor -= detailHeight + (compact ? 6 : 12);
    CGFloat progressWidth = fmin(contentWidth, compact ? 260 : 360);
    _progress.frame = NSMakeRect(floor((width-progressWidth)/2), cursor-8, progressWidth, 8);
    _footer.frame = NSMakeRect(left, 22, contentWidth, 16);
    [self setNeedsDisplay:YES];
}

-(void)drawRect:(NSRect)dirtyRect {
    (void)dirtyRect;
    NSRect bounds = self.bounds;
    CGFloat width = NSWidth(bounds), height = NSHeight(bounds);
    NSGradient *background = [[NSGradient alloc] initWithStartingColor:
        [NSColor colorWithCalibratedRed:0.025 green:0.065 blue:0.047 alpha:1]
        endingColor:[NSColor colorWithCalibratedRed:0.09 green:0.21 blue:0.15 alpha:1]];
    [background drawInRect:bounds angle:55];
    /* Original, static contour artwork: no game textures and no render timer. */
    [[NSColor colorWithCalibratedRed:0.65 green:0.70 blue:0.45 alpha:0.075] setStroke];
    for (int i = 0; i < 6; i++) {
        CGFloat radius = 50+i*54;
        NSBezierPath *ring = [NSBezierPath bezierPathWithOvalInRect:
            NSMakeRect(width*0.86-radius, height*0.82-radius, radius*2, radius*2)];
        ring.lineWidth = 1;
        [ring stroke];
    }
    for (int i = 0; i < 3; i++) {
        CGFloat base = height*(0.10+i*0.045);
        NSBezierPath *hill = [NSBezierPath bezierPath];
        [hill moveToPoint:NSMakePoint(0, 0)];
        [hill lineToPoint:NSMakePoint(0, base)];
        [hill curveToPoint:NSMakePoint(width, base+height*0.04)
            controlPoint1:NSMakePoint(width*0.32, base+height*0.13)
            controlPoint2:NSMakePoint(width*0.68, base-height*0.10)];
        [hill lineToPoint:NSMakePoint(width, 0)];
        [hill closePath];
        [[NSColor colorWithCalibratedRed:0.02 green:0.07 blue:0.045 alpha:0.24-i*0.05] setFill];
        [hill fill];
    }
    if (_mark.image && NSHeight(bounds) >= 420) {
        [[NSColor colorWithCalibratedRed:0.94 green:0.95 blue:0.85 alpha:0.96] setFill];
        [[NSBezierPath bezierPathWithOvalInRect:NSInsetRect(_mark.frame, -10, -10)] fill];
    }
}
@end
