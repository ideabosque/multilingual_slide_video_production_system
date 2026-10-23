import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {SlideFrame} from './SlideFrame';
import type {SlideshowProps} from './types';

// One Sequence per timing item (title card, then each slide). Inside a
// Sequence, useCurrentFrame() is local to the clip, matching HyperFrames'
// clip-local timelines.
export const Slideshow: React.FC<SlideshowProps> = ({clips, width, height}) => (
	<AbsoluteFill style={{backgroundColor: '#000'}}>
		{clips.map((clip) => (
			<Sequence key={clip.id} name={clip.id} from={clip.from} durationInFrames={clip.durationInFrames}>
				<SlideFrame clip={clip} width={width} height={height} />
			</Sequence>
		))}
	</AbsoluteFill>
);
