import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Sequence,
  Easing,
} from "remotion";

// Vibrant color palette
const COLORS = {
  bgStart: "#0f0c29",
  bgMid: "#302b63",
  bgEnd: "#24243e",
  primary: "#00ff87", // Vibrant green
  primaryDark: "#00cc6a",
  secondary: "#00d4ff", // Vibrant cyan
  error: "#ff4757", // Vibrant red
  errorDark: "#c0392b",
  gold: "#ffd32a",
  white: "#ffffff",
  dimText: "rgba(255,255,255,0.6)",
};

// Reusable Die Component
const Die: React.FC<{
  value: number;
  size?: number;
  highlight?: "keep" | "reroll" | "none";
  style?: React.CSSProperties;
}> = ({ value, size = 90, highlight = "none", style }) => {
  const dotPositions: { [key: number]: Array<{ cx: number; cy: number }> } = {
    1: [{ cx: 50, cy: 50 }],
    2: [{ cx: 28, cy: 28 }, { cx: 72, cy: 72 }],
    3: [{ cx: 28, cy: 28 }, { cx: 50, cy: 50 }, { cx: 72, cy: 72 }],
    4: [{ cx: 28, cy: 28 }, { cx: 72, cy: 28 }, { cx: 28, cy: 72 }, { cx: 72, cy: 72 }],
    5: [{ cx: 28, cy: 28 }, { cx: 72, cy: 28 }, { cx: 50, cy: 50 }, { cx: 28, cy: 72 }, { cx: 72, cy: 72 }],
    6: [{ cx: 28, cy: 25 }, { cx: 72, cy: 25 }, { cx: 28, cy: 50 }, { cx: 72, cy: 50 }, { cx: 28, cy: 75 }, { cx: 72, cy: 75 }],
  };

  const bgColor = highlight === "keep"
    ? `linear-gradient(145deg, ${COLORS.primary}, ${COLORS.primaryDark})`
    : highlight === "reroll"
    ? `linear-gradient(145deg, ${COLORS.error}, ${COLORS.errorDark})`
    : "linear-gradient(145deg, #ffffff, #e0e0e0)";

  const dotColor = highlight === "none" ? "#1a1a2e" : "#ffffff";

  return (
    <div
      style={{
        width: size,
        height: size,
        background: bgColor,
        borderRadius: size * 0.15,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: highlight === "keep"
          ? `0 0 30px ${COLORS.primary}, 0 8px 25px rgba(0,0,0,0.4)`
          : highlight === "reroll"
          ? `0 0 30px ${COLORS.error}, 0 8px 25px rgba(0,0,0,0.4)`
          : "0 8px 25px rgba(0,0,0,0.4)",
        ...style,
      }}
    >
      <svg width={size * 0.8} height={size * 0.8} viewBox="0 0 100 100">
        {dotPositions[value]?.map((pos, i) => (
          <circle key={i} cx={pos.cx} cy={pos.cy} r="11" fill={dotColor} />
        ))}
      </svg>
    </div>
  );
};

// Win Probability Bar Component
const WinProbBar: React.FC<{
  probability: number;
  isError?: boolean;
  label?: string;
}> = ({ probability, isError = false, label = "Win Probability" }) => {
  const barColor = isError
    ? `linear-gradient(90deg, ${COLORS.error}, ${COLORS.errorDark})`
    : `linear-gradient(90deg, ${COLORS.primary}, ${COLORS.secondary})`;

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <span style={{
          fontSize: 32,
          fontWeight: 600,
          color: COLORS.white,
          fontFamily: "system-ui, sans-serif",
        }}>
          {label}
        </span>
        <span style={{
          fontSize: 32,
          fontWeight: 800,
          color: isError ? COLORS.error : COLORS.primary,
          fontFamily: "system-ui, sans-serif",
        }}>
          {Math.round(probability)}%
        </span>
      </div>
      <div style={{
        height: 24,
        background: "rgba(255,255,255,0.1)",
        borderRadius: 12,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${probability}%`,
          height: "100%",
          background: barColor,
          borderRadius: 12,
          boxShadow: isError ? `0 0 20px ${COLORS.error}` : `0 0 20px ${COLORS.primary}`,
        }} />
      </div>
    </div>
  );
};

// Scene 1: Setup - Show the roll (0-3s)
const SetupScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleOpacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const diceDelays = [15, 22, 29, 36, 43];
  const diceValues = [6, 6, 6, 5, 4];

  const probProgress = interpolate(frame, [50, 80], [0, 62], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  return (
    <AbsoluteFill style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      padding: 80,
    }}>
      {/* Title */}
      <div style={{ opacity: titleOpacity, marginBottom: 60 }}>
        <h2 style={{
          fontSize: 64,
          fontWeight: 300,
          color: COLORS.dimText,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          letterSpacing: 4,
        }}>
          Your Roll
        </h2>
      </div>

      {/* Dice */}
      <div style={{ display: "flex", gap: 30, marginBottom: 80 }}>
        {diceValues.map((val, i) => {
          const scale = spring({
            frame,
            fps,
            delay: diceDelays[i],
            config: { damping: 12, stiffness: 80 },
          });
          return (
            <div key={i} style={{ transform: `scale(${scale})` }}>
              <Die value={val} size={110} />
            </div>
          );
        })}
      </div>

      {/* Win Probability */}
      <div style={{ width: 700, opacity: interpolate(frame, [45, 60], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
        <WinProbBar probability={probProgress} />
      </div>
    </AbsoluteFill>
  );
};

// Scene 2: Bad Move - User makes wrong choice (3-6s)
const BadMoveScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const diceValues = [6, 6, 6, 5, 4];
  // Bad move: keeping only 5, 4 and rerolling the 6s (terrible!)
  const keepIndices = [3, 4]; // indices of dice to keep (5 and 4)

  const titleOpacity = interpolate(frame, [0, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const selectionOpacity = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Probability drops from 62% to 31%
  const probDrop = interpolate(frame, [55, 85], [62, 31], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Screen shake when probability drops
  const shakeIntensity = interpolate(frame, [55, 65, 85], [0, 8, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const shakeX = Math.sin(frame * 1.5) * shakeIntensity;
  const shakeY = Math.cos(frame * 2) * shakeIntensity;

  // Red flash
  const redFlash = interpolate(frame, [55, 65, 85], [0, 0.15, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      padding: 80,
      transform: `translate(${shakeX}px, ${shakeY}px)`,
    }}>
      {/* Red overlay flash */}
      <AbsoluteFill style={{
        background: COLORS.error,
        opacity: redFlash,
        pointerEvents: "none",
      }} />

      {/* Title */}
      <div style={{ opacity: titleOpacity, marginBottom: 50 }}>
        <h2 style={{
          fontSize: 56,
          fontWeight: 600,
          color: COLORS.error,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
        }}>
          Player's Choice...
        </h2>
      </div>

      {/* Dice with selections */}
      <div style={{ display: "flex", gap: 30, marginBottom: 40, opacity: selectionOpacity }}>
        {diceValues.map((val, i) => {
          const isKeep = keepIndices.includes(i);
          return (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 15 }}>
              <Die value={val} size={100} highlight={isKeep ? "keep" : "reroll"} />
              <span style={{
                fontSize: 24,
                fontWeight: 700,
                color: isKeep ? COLORS.primary : COLORS.error,
                fontFamily: "system-ui, sans-serif",
                textTransform: "uppercase",
                letterSpacing: 2,
              }}>
                {isKeep ? "Keep" : "Reroll"}
              </span>
            </div>
          );
        })}
      </div>

      {/* Bad decision text */}
      <div style={{
        opacity: selectionOpacity,
        marginBottom: 50,
        textAlign: "center",
      }}>
        <p style={{
          fontSize: 36,
          color: COLORS.dimText,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
        }}>
          Rerolling three 6s for a straight?!
        </p>
      </div>

      {/* Win Probability dropping */}
      <div style={{ width: 700 }}>
        <WinProbBar probability={probDrop} isError={probDrop < 50} />
      </div>
    </AbsoluteFill>
  );
};

// Scene 3: X-Out Warning (6-9s)
const WarningScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Big X animation
  const xScale = spring({
    frame,
    fps,
    delay: 0,
    config: { damping: 8, stiffness: 60 },
  });

  const xRotation = interpolate(
    spring({ frame, fps, delay: 0, config: { damping: 15 } }),
    [0, 1],
    [-180, 0]
  );

  // Text fade in
  const textOpacity = interpolate(frame, [40, 70], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const textY = interpolate(frame, [40, 70], [30, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Pulsing glow on X
  const glowPulse = interpolate(frame, [0, 30, 60, 90], [0.5, 1, 0.5, 1], {
    extrapolateRight: "extend",
  });

  return (
    <AbsoluteFill style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
    }}>
      {/* Big Red X */}
      <div style={{
        transform: `scale(${xScale}) rotate(${xRotation}deg)`,
        marginBottom: 60,
      }}>
        <svg width="300" height="300" viewBox="0 0 100 100">
          <line
            x1="15" y1="15" x2="85" y2="85"
            stroke={COLORS.error}
            strokeWidth="12"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 ${30 * glowPulse}px ${COLORS.error})` }}
          />
          <line
            x1="85" y1="15" x2="15" y2="85"
            stroke={COLORS.error}
            strokeWidth="12"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 ${30 * glowPulse}px ${COLORS.error})` }}
          />
        </svg>
      </div>

      {/* Warning Text */}
      <div style={{
        opacity: textOpacity,
        transform: `translateY(${textY}px)`,
        textAlign: "center",
      }}>
        <h1 style={{
          fontSize: 72,
          fontWeight: 900,
          color: COLORS.white,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          marginBottom: 20,
          textShadow: `0 0 40px ${COLORS.error}`,
        }}>
          Never Make Mistakes
        </h1>
        <h1 style={{
          fontSize: 72,
          fontWeight: 900,
          color: COLORS.error,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          textShadow: `0 0 40px ${COLORS.error}`,
        }}>
          Like This Again
        </h1>
      </div>
    </AbsoluteFill>
  );
};

// Scene 4: ysolver Solution (9-15s)
const YsolverScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const diceValues = [6, 6, 6, 5, 4];
  const keepIndices = [0, 1, 2]; // Keep the three 6s!

  // Card entrance
  const cardScale = spring({
    frame,
    fps,
    delay: 0,
    config: { damping: 18, stiffness: 60 },
  });

  // Logo/title
  const logoOpacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Dice appearance
  const diceOpacity = interpolate(frame, [35, 55], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Recommendation text
  const recOpacity = interpolate(frame, [60, 85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Probability RISES from 31% to 78%
  const probRise = interpolate(frame, [90, 150], [31, 78], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Green glow pulse for success
  const successGlow = interpolate(frame, [120, 140, 160, 180], [0, 1, 0.5, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  return (
    <AbsoluteFill style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      {/* Success glow overlay */}
      <AbsoluteFill style={{
        background: `radial-gradient(circle at center, ${COLORS.primary}22 0%, transparent 70%)`,
        opacity: successGlow * 0.5,
        pointerEvents: "none",
      }} />

      {/* Main Card */}
      <div style={{
        transform: `scale(${cardScale})`,
        width: 1000,
        background: "rgba(255,255,255,0.03)",
        borderRadius: 40,
        padding: 60,
        backdropFilter: "blur(30px)",
        border: `2px solid ${COLORS.primary}40`,
        boxShadow: `0 30px 80px rgba(0,0,0,0.5), 0 0 ${60 * successGlow}px ${COLORS.primary}40`,
      }}>
        {/* ysolver Logo */}
        <div style={{ textAlign: "center", marginBottom: 50, opacity: logoOpacity }}>
          <h1 style={{
            fontSize: 80,
            fontWeight: 900,
            fontFamily: "system-ui, sans-serif",
            margin: 0,
            background: `linear-gradient(135deg, ${COLORS.primary}, ${COLORS.secondary})`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            filter: `drop-shadow(0 0 30px ${COLORS.primary}60)`,
          }}>
            ysolver
          </h1>
          <p style={{
            fontSize: 24,
            color: COLORS.dimText,
            margin: 0,
            marginTop: 10,
            letterSpacing: 6,
            textTransform: "uppercase",
          }}>
            Optimal Play Engine
          </p>
        </div>

        {/* Dice with CORRECT selections */}
        <div style={{
          display: "flex",
          justifyContent: "center",
          gap: 25,
          marginBottom: 40,
          opacity: diceOpacity,
        }}>
          {diceValues.map((val, i) => {
            const isKeep = keepIndices.includes(i);
            return (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                <Die value={val} size={90} highlight={isKeep ? "keep" : "reroll"} />
                <span style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: isKeep ? COLORS.primary : COLORS.error,
                  fontFamily: "system-ui, sans-serif",
                  textTransform: "uppercase",
                  letterSpacing: 2,
                }}>
                  {isKeep ? "Keep" : "Reroll"}
                </span>
              </div>
            );
          })}
        </div>

        {/* Recommendation */}
        <div style={{ textAlign: "center", marginBottom: 50, opacity: recOpacity }}>
          <p style={{
            fontSize: 22,
            color: COLORS.dimText,
            margin: 0,
            marginBottom: 8,
          }}>
            Optimal Move
          </p>
          <p style={{
            fontSize: 44,
            fontWeight: 700,
            color: COLORS.primary,
            fontFamily: "system-ui, sans-serif",
            margin: 0,
            textShadow: `0 0 30px ${COLORS.primary}60`,
          }}>
            Keep 6, 6, 6 — Go for Yahtzee!
          </p>
        </div>

        {/* Win Probability RISING */}
        <WinProbBar probability={probRise} isError={false} />
      </div>
    </AbsoluteFill>
  );
};

// Scene 5: CTA (15-20s)
const CTAScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({
    frame,
    fps,
    delay: 0,
    config: { damping: 15, stiffness: 50 },
  });

  const taglineOpacity = interpolate(frame, [40, 70], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const taglineY = interpolate(frame, [40, 70], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Animated gradient glow
  const glowPhase = (frame / 60) * Math.PI * 2;
  const glowIntensity = 0.7 + 0.3 * Math.sin(glowPhase);

  return (
    <AbsoluteFill style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
    }}>
      {/* Radial glow background */}
      <AbsoluteFill style={{
        background: `radial-gradient(ellipse at center, ${COLORS.primary}15 0%, transparent 60%)`,
        opacity: glowIntensity,
      }} />

      {/* Main Logo */}
      <div style={{
        transform: `scale(${logoScale})`,
        textAlign: "center",
        marginBottom: 50,
      }}>
        <h1 style={{
          fontSize: 160,
          fontWeight: 900,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          background: `linear-gradient(135deg, ${COLORS.primary}, ${COLORS.secondary}, ${COLORS.gold})`,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          filter: `drop-shadow(0 0 ${50 * glowIntensity}px ${COLORS.primary}80)`,
        }}>
          ysolver
        </h1>
      </div>

      {/* Tagline */}
      <div style={{
        opacity: taglineOpacity,
        transform: `translateY(${taglineY}px)`,
        textAlign: "center",
      }}>
        <p style={{
          fontSize: 48,
          fontWeight: 600,
          color: COLORS.white,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          marginBottom: 20,
        }}>
          Never Blunder Again
        </p>
        <p style={{
          fontSize: 28,
          fontWeight: 400,
          color: COLORS.secondary,
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          letterSpacing: 8,
          textTransform: "uppercase",
        }}>
          Optimal Yahtzee Strategy
        </p>
      </div>
    </AbsoluteFill>
  );
};

// Main Composition
export const YahtzeeSolverAd: React.FC = () => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(135deg, ${COLORS.bgStart} 0%, ${COLORS.bgMid} 50%, ${COLORS.bgEnd} 100%)`,
      }}
    >
      {/* Scene 1: Setup - Show the roll (0-3s) */}
      <Sequence from={0} durationInFrames={3 * fps} premountFor={fps}>
        <SetupScene />
      </Sequence>

      {/* Scene 2: Bad Move (3-6s) */}
      <Sequence from={3 * fps} durationInFrames={3 * fps} premountFor={fps}>
        <BadMoveScene />
      </Sequence>

      {/* Scene 3: X-Out Warning (6-9s) */}
      <Sequence from={6 * fps} durationInFrames={3 * fps} premountFor={fps}>
        <WarningScene />
      </Sequence>

      {/* Scene 4: ysolver Solution (9-15s) */}
      <Sequence from={9 * fps} durationInFrames={6 * fps} premountFor={fps}>
        <YsolverScene />
      </Sequence>

      {/* Scene 5: CTA (15-20s) */}
      <Sequence from={15 * fps} durationInFrames={5 * fps} premountFor={fps}>
        <CTAScene />
      </Sequence>
    </AbsoluteFill>
  );
};
