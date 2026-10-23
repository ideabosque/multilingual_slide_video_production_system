import type React from 'react';
import type {Transition} from './types';

// The same transitions the runtime plays on a slide's root in HyperFrames
// (animation_runtime.js addTransition), on the iframe instead: a crossfade
// or wipe moves only the incoming slide, which sits on top; a push moves
// both. Eases match GSAP's: "none" and power2.inOut (a cubic in-out).
const cubicInOut = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);

const progress = (frame: number, start: number, frames: number) =>
	Math.min(1, Math.max(0, (frame - start) / frames));

const WIPE_HIDDEN: Record<Transition['direction'], (p: number) => string> = {
	left: (p) => `inset(0% 0% 0% ${p}%)`,
	right: (p) => `inset(0% ${p}% 0% 0%)`,
	up: (p) => `inset(${p}% 0% 0% 0%)`,
	down: (p) => `inset(0% 0% ${p}% 0%)`,
};

const pushOffset = (t: Transition, amount: number): string => {
	const horizontal = t.direction === 'left' || t.direction === 'right';
	const sign = t.direction === 'left' || t.direction === 'up' ? 1 : -1;
	const value = `${amount * sign}%`;
	return horizontal ? `translateX(${value})` : `translateY(${value})`;
};

export const transitionStyle = (frame: number, enter?: Transition, exit?: Transition): React.CSSProperties => {
	const style: React.CSSProperties = {};
	const transforms: string[] = [];
	if (enter && frame < enter.frames) {
		const p = progress(frame, 0, enter.frames);
		if (enter.type === 'crossfade') style.opacity = p;
		if (enter.type === 'push') transforms.push(pushOffset(enter, 100 * (1 - cubicInOut(p))));
		if (enter.type === 'wipe') style.clipPath = WIPE_HIDDEN[enter.direction](100 * (1 - cubicInOut(p)));
	}
	if (exit && exit.type === 'push' && frame >= (exit.start ?? 0)) {
		const p = progress(frame, exit.start ?? 0, exit.frames);
		transforms.push(pushOffset(exit, -100 * cubicInOut(p)));
	}
	if (transforms.length) style.transform = transforms.join(' ');
	return style;
};
