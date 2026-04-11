import React from 'react';
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

interface KeyPoint {
  heading: string;
  body: string;
}

interface SlideData {
  title: string;
  subtitle: string;
  summary: string[];      // 3-5 items
  keyPoints: KeyPoint[];  // 1-4 items
  takeaway: string;
  source: string;
}

interface ThemeColors {
  primary?: string;
  accent?: string;
  bg?: string;
  fg?: string;
  muted?: string;
}

interface ThemeFonts {
  heading?: string;
  body?: string;
}

export interface Theme {
  colors?: ThemeColors;
  fonts?: ThemeFonts;
  logo?: string;       // filename relative to public/ (e.g. "logo.svg")
  logoLight?: string;  // filename relative to public/, for dark backgrounds
  footer?: string;
}

// REPLACE: fill with actual research data from Step 4
const slideData: SlideData = {
  title: 'PLACEHOLDER_TITLE',
  subtitle: 'PLACEHOLDER_SUBTITLE',
  summary: [
    'PLACEHOLDER_SUMMARY_1',
    'PLACEHOLDER_SUMMARY_2',
    'PLACEHOLDER_SUMMARY_3',
  ],
  keyPoints: [
    { heading: 'PLACEHOLDER_KEYPOINT_HEADING_1', body: 'PLACEHOLDER_KEYPOINT_BODY_1' },
    { heading: 'PLACEHOLDER_KEYPOINT_HEADING_2', body: 'PLACEHOLDER_KEYPOINT_BODY_2' },
    { heading: 'PLACEHOLDER_KEYPOINT_HEADING_3', body: 'PLACEHOLDER_KEYPOINT_BODY_3' },
    { heading: 'PLACEHOLDER_KEYPOINT_HEADING_4', body: 'PLACEHOLDER_KEYPOINT_BODY_4' },
  ],
  takeaway: 'PLACEHOLDER_TAKEAWAY',
  source: 'PLACEHOLDER_SOURCE',
};

// Built-in defaults used when no brand theme is provided
const DEFAULT_BG = 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)';
const DEFAULT_PRIMARY = '#0f3460';
const DEFAULT_FG = '#ffffff';
const DEFAULT_CONTENT_BG = '#ffffff';
const DEFAULT_CONTENT_FG = '#222222';
const DEFAULT_HEADING_COLOR = '#1a1a2e';
const DEFAULT_MUTED_DARK = 'rgba(255,255,255,0.7)';
const DEFAULT_MUTED_LIGHT = 'rgba(0,0,0,0.5)';
const DEFAULT_FONT = 'Helvetica Neue, Arial, sans-serif';

interface SlideProps {
  theme: Theme;
}

// --- Logo overlay (top-right corner) ---
const LogoOverlay: React.FC<{ logoFile: string | undefined }> = ({ logoFile }) => {
  if (!logoFile) return null;
  return (
    <div
      style={{
        position: 'absolute',
        top: 20,
        right: 28,
        zIndex: 100,
      }}
    >
      <Img src={staticFile(logoFile)} style={{ height: 36, width: 'auto' }} />
    </div>
  );
};

// --- Footer bar ---
const FooterBar: React.FC<{ text: string | undefined; muted: string }> = ({ text, muted }) => {
  if (!text) return null;
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 20,
        left: 0,
        right: 0,
        textAlign: 'center',
        fontSize: 14,
        color: muted,
      }}
    >
      {text}
    </div>
  );
};

// Helper: resolve font-family string from optional theme font name
const fontFamily = (name: string | undefined): string =>
  name ? `${name}, sans-serif` : DEFAULT_FONT;

// --- Slide 1: Title ---
const TitleSlide: React.FC<SlideProps> = ({ theme }) => {
  const frame = useCurrentFrame();

  const bg = theme.colors?.bg ?? DEFAULT_BG;
  const fg = theme.colors?.fg ?? DEFAULT_FG;
  const logoFile = theme.logoLight ?? theme.logo;

  const titleOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: 'clamp' });
  const titleY = interpolate(frame, [0, 20], [20, 0], { extrapolateRight: 'clamp' });

  const subtitleOpacity = interpolate(frame, [10, 30], [0, 1], { extrapolateRight: 'clamp' });
  const subtitleY = interpolate(frame, [10, 30], [20, 0], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill
      style={{
        background: bg,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '60px',
        fontFamily: fontFamily(theme.fonts?.body),
      }}
    >
      <LogoOverlay logoFile={logoFile} />
      <div
        style={{
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          fontSize: '64px',
          fontWeight: 700,
          color: fg,
          textAlign: 'center',
          lineHeight: 1.2,
          marginBottom: '24px',
          fontFamily: fontFamily(theme.fonts?.heading),
        }}
      >
        {slideData.title}
      </div>
      <div
        style={{
          opacity: subtitleOpacity,
          transform: `translateY(${subtitleY}px)`,
          fontSize: '28px',
          fontWeight: 300,
          color: `${fg}cc`,
          textAlign: 'center',
          maxWidth: '900px',
        }}
      >
        {slideData.subtitle}
      </div>
      <FooterBar text={theme.footer} muted={theme.colors?.muted ?? DEFAULT_MUTED_DARK} />
    </AbsoluteFill>
  );
};

// --- Slide 2: Summary / Overview ---
const SummarySlide: React.FC<SlideProps> = ({ theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headingColor = theme.colors?.primary ?? DEFAULT_HEADING_COLOR;
  const bulletColor = theme.colors?.primary ?? DEFAULT_PRIMARY;
  const textColor = theme.colors?.fg ?? DEFAULT_CONTENT_FG;
  const logoFile = theme.logo ?? theme.logoLight;

  return (
    <AbsoluteFill
      style={{
        background: DEFAULT_CONTENT_BG,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '80px',
        fontFamily: fontFamily(theme.fonts?.body),
      }}
    >
      <LogoOverlay logoFile={logoFile} />
      <div
        style={{
          fontSize: '42px',
          fontWeight: 700,
          color: headingColor,
          marginBottom: '40px',
          fontFamily: fontFamily(theme.fonts?.heading),
        }}
      >
        Overview
      </div>
      {slideData.summary.map((bullet, index) => {
        const delay = index * 10;
        const progress = spring({
          frame: frame - delay,
          fps,
          config: { damping: 14, stiffness: 100, mass: 1 },
        });
        const opacity = interpolate(progress, [0, 1], [0, 1]);
        const translateX = interpolate(progress, [0, 1], [-20, 0]);

        return (
          <div
            key={index}
            style={{
              opacity,
              transform: `translateX(${translateX}px)`,
              display: 'flex',
              alignItems: 'flex-start',
              marginBottom: '20px',
            }}
          >
            <span
              style={{
                fontSize: '22px',
                color: bulletColor,
                marginRight: '16px',
                marginTop: '2px',
                flexShrink: 0,
              }}
            >
              -
            </span>
            <span style={{ fontSize: '26px', color: textColor, lineHeight: 1.4 }}>
              {bullet}
            </span>
          </div>
        );
      })}
      <FooterBar text={theme.footer} muted={theme.colors?.muted ?? DEFAULT_MUTED_LIGHT} />
    </AbsoluteFill>
  );
};

// --- Key Point Slide (reusable) ---
interface KeyPointSlideProps extends SlideProps {
  keyPoint?: KeyPoint;
}

const KeyPointSlide: React.FC<KeyPointSlideProps> = ({ keyPoint, theme }) => {
  const frame = useCurrentFrame();

  const headingColor = theme.colors?.primary ?? DEFAULT_HEADING_COLOR;
  const borderColor = theme.colors?.primary ?? DEFAULT_PRIMARY;
  const bodyColor = theme.colors?.fg ?? '#333333';
  const logoFile = theme.logo ?? theme.logoLight;

  const headingX = interpolate(frame, [0, 15], [-30, 0], { extrapolateRight: 'clamp' });
  const headingOpacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });

  const bodyOpacity = interpolate(frame, [15, 30], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill
      style={{
        background: DEFAULT_CONTENT_BG,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '80px',
        fontFamily: fontFamily(theme.fonts?.body),
      }}
    >
      <LogoOverlay logoFile={logoFile} />
      <div
        style={{
          opacity: headingOpacity,
          transform: `translateX(${headingX}px)`,
          fontSize: '42px',
          fontWeight: 700,
          color: headingColor,
          marginBottom: '32px',
          borderLeft: `6px solid ${borderColor}`,
          paddingLeft: '24px',
          fontFamily: fontFamily(theme.fonts?.heading),
        }}
      >
        {keyPoint?.heading ?? ''}
      </div>
      <div
        style={{
          opacity: bodyOpacity,
          fontSize: '26px',
          color: bodyColor,
          lineHeight: 1.6,
          maxWidth: '1000px',
        }}
      >
        {keyPoint?.body ?? ''}
      </div>
      <FooterBar text={theme.footer} muted={theme.colors?.muted ?? DEFAULT_MUTED_LIGHT} />
    </AbsoluteFill>
  );
};

// --- Slide 7: Takeaway ---
const TakeawaySlide: React.FC<SlideProps> = ({ theme }) => {
  const frame = useCurrentFrame();

  const bg = theme.colors?.bg ?? DEFAULT_BG;
  const fg = theme.colors?.fg ?? DEFAULT_FG;
  const logoFile = theme.logoLight ?? theme.logo;
  const mutedColor = theme.colors?.muted ?? DEFAULT_MUTED_DARK;

  const takeawayOpacity = interpolate(frame, [0, 25], [0, 1], { extrapolateRight: 'clamp' });
  const sourceOpacity = interpolate(frame, [20, 40], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill
      style={{
        background: bg,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '80px',
        fontFamily: fontFamily(theme.fonts?.body),
      }}
    >
      <LogoOverlay logoFile={logoFile} />
      <div
        style={{
          opacity: takeawayOpacity,
          fontSize: '34px',
          fontWeight: 400,
          color: fg,
          textAlign: 'center',
          lineHeight: 1.6,
          maxWidth: '960px',
          marginBottom: '48px',
        }}
      >
        {slideData.takeaway}
      </div>
      {slideData.source ? (
        <div
          style={{
            opacity: sourceOpacity * 0.6,
            fontSize: '18px',
            color: mutedColor,
            textAlign: 'center',
            position: 'absolute',
            bottom: theme.footer ? '44px' : '48px',
          }}
        >
          Source: {slideData.source}
        </div>
      ) : null}
      <FooterBar text={theme.footer} muted={mutedColor} />
    </AbsoluteFill>
  );
};

// --- Root composition ---
export interface ResearchSlidesProps {
  theme: Theme;
}

export const ResearchSlides: React.FC<ResearchSlidesProps> = ({ theme }) => {
  return (
    <AbsoluteFill style={{ fontFamily: fontFamily(theme.fonts?.body) }}>
      {/* Slide 1: Title (frames 0-149) */}
      <Sequence from={0} durationInFrames={150}>
        <TitleSlide theme={theme} />
      </Sequence>

      {/* Slide 2: Summary (frames 150-299) */}
      <Sequence from={150} durationInFrames={150}>
        <SummarySlide theme={theme} />
      </Sequence>

      {/* Slide 3: Key Point 1 (frames 300-449) */}
      <Sequence from={300} durationInFrames={150}>
        <KeyPointSlide keyPoint={slideData.keyPoints[0]} theme={theme} />
      </Sequence>

      {/* Slide 4: Key Point 2 (frames 450-599) */}
      <Sequence from={450} durationInFrames={150}>
        <KeyPointSlide keyPoint={slideData.keyPoints[1]} theme={theme} />
      </Sequence>

      {/* Slide 5: Key Point 3 (frames 600-749) */}
      <Sequence from={600} durationInFrames={150}>
        <KeyPointSlide keyPoint={slideData.keyPoints[2]} theme={theme} />
      </Sequence>

      {/* Slide 6: Key Point 4 (frames 750-899) */}
      <Sequence from={750} durationInFrames={150}>
        <KeyPointSlide keyPoint={slideData.keyPoints[3]} theme={theme} />
      </Sequence>

      {/* Slide 7: Takeaway (frames 900-1049) */}
      <Sequence from={900} durationInFrames={150}>
        <TakeawaySlide theme={theme} />
      </Sequence>
    </AbsoluteFill>
  );
};

ResearchSlides.defaultProps = {
  theme: {},
};
