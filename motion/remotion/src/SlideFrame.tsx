import React, {useCallback, useLayoutEffect, useRef, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {transitionStyle} from './transitions';
import type {Clip} from './types';

type SlideWindow = Window & {
	__timelines?: Record<string, {seek: (t: number) => unknown}>;
	__motionErrors?: string[];
};

// The deck-faithful mode (plan B5): the translated slide itself, in an
// iframe, with the same seek-mode animation runtime HyperFrames uses. Every
// frame seeks the slide's paused GSAP timeline to frame / fps, so each frame
// is a pure function of the frame number. Transitions to the neighbouring
// slides play on the iframe (transitions.ts).
export const SlideFrame: React.FC<{clip: Clip; width: number; height: number}> = ({clip, width, height}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const ref = useRef<HTMLIFrameElement>(null);
	const [handle] = useState(() => delayRender(`loading slide ${clip.id}`));
	const [ready, setReady] = useState(false);
	const released = useRef(false);

	const onLoad = useCallback(() => {
		const win = ref.current?.contentWindow as SlideWindow | null;
		if (!win) {
			cancelRender(new Error(`${clip.id}: the slide page did not load`));
			return;
		}
		win.document.fonts.ready.then(() => {
			const errors = win.__motionErrors || [];
			if (errors.length) {
				throw new Error(`${clip.id}: script error in the slide page: ${errors.join(' | ')}`);
			}
			if (!win.__timelines || !win.__timelines[clip.id]) {
				throw new Error(`${clip.id}: the slide's animation timeline never registered`);
			}
			setReady(true);
		}).catch((err) => cancelRender(err));
	}, [clip.id]);

	useLayoutEffect(() => {
		if (!ready) return;
		const win = ref.current?.contentWindow as SlideWindow | null;
		try {
			win!.__timelines![clip.id].seek(frame / fps);
		} catch (err) {
			cancelRender(err);
			return;
		}
		if (!released.current) {
			released.current = true;
			continueRender(handle);
		}
	}, [ready, frame, fps, clip.id, handle]);

	return (
		<iframe
			ref={ref}
			src={staticFile(clip.src)}
			onLoad={onLoad}
			style={{
				position: 'absolute', left: 0, top: 0, width, height, border: 0, display: 'block',
				backgroundColor: '#000', ...transitionStyle(frame, clip.enter, clip.exit),
			}}
		/>
	);
};
