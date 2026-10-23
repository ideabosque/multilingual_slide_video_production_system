import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {Slideshow} from './Slideshow';
import type {SlideshowProps} from './types';

const calculateMetadata: CalculateMetadataFunction<SlideshowProps> = ({props}) => ({
	durationInFrames: props.durationInFrames,
	fps: props.fps,
	width: props.width,
	height: props.height,
});

export const Root: React.FC = () => (
	<Composition
		id="Slideshow"
		component={Slideshow}
		durationInFrames={1}
		fps={30}
		width={1920}
		height={1080}
		defaultProps={{width: 1920, height: 1080, fps: 30, durationInFrames: 1, clips: []}}
		calculateMetadata={calculateMetadata}
	/>
);
