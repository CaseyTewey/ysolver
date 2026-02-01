import { Composition } from "remotion";
import { YahtzeeSolverAd } from "./YahtzeeSolverAd";

export const RemotionRoot = () => {
  return (
    <Composition
      id="ysolver-ad"
      component={YahtzeeSolverAd}
      durationInFrames={600}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
