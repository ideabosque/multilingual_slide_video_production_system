// The input props remotion_engine.py writes (props.json). Every number is
// decided in Python (production/motion/clips.py): clip boundaries are whole
// frames from the same plan HyperFrames uses, so both engines cut,
// choreograph and transition every slide on the same frames.
export type Transition = {
	type: 'crossfade' | 'push' | 'wipe';
	direction: 'left' | 'right' | 'up' | 'down';
	frames: number;
	// Outgoing half only: the clip-local frame it starts on.
	start?: number;
};

export type Clip = {
	// The slide id; also the key of the page's window.__timelines entry.
	id: string;
	// Page path relative to the bundle's public dir (served via staticFile).
	src: string;
	// The clip's frames, including any transition overlap with its neighbours.
	from: number;
	durationInFrames: number;
	enter?: Transition;
	exit?: Transition;
};

export type SlideshowProps = {
	width: number;
	height: number;
	fps: number;
	durationInFrames: number;
	clips: Clip[];
};
