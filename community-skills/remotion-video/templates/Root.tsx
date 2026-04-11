import React from 'react';
import { Composition } from 'remotion';
import { ResearchSlides } from './ResearchSlides';
import type { ResearchSlidesProps } from './ResearchSlides';

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="ResearchSlides"
        component={ResearchSlides}
        durationInFrames={1050}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{ theme: {} } as ResearchSlidesProps}
      />
    </>
  );
};
