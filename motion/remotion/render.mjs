// Renders the Slideshow composition to a silent H.264 video. Called by
// remotion_engine.py, never by hand: every argument is decided in Python.
//
//   node render.mjs <args.json>
//
// args.json: {publicDir, bundleDir, props, output, crf, x264Preset,
//             concurrency, scale, browserExecutable, timeoutMs}
//
// Prints one JSON line: {"ok": true, "frames": n} or {"ok": false, "error": "..."}.
// The browser is the chrome-headless-shell `msv motion install` downloaded;
// it is passed explicitly so a render never downloads anything.
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const browserErrors = [];

try {
	const serveUrl = await bundle({
		entryPoint: path.join(here, 'src', 'index.ts'),
		publicDir: args.publicDir,
		outDir: args.bundleDir,
	});
	const common = {
		serveUrl,
		inputProps: args.props,
		browserExecutable: args.browserExecutable,
		timeoutInMilliseconds: args.timeoutMs,
		logLevel: 'error',
		onBrowserLog: (log) => {
			if (log.type === 'error') browserErrors.push(log.text);
		},
	};
	const composition = await selectComposition({...common, id: 'Slideshow'});
	await renderMedia({
		...common,
		composition,
		codec: 'h264',
		muted: true,
		crf: args.crf,
		x264Preset: args.x264Preset,
		pixelFormat: 'yuv420p',
		concurrency: args.concurrency,
		scale: args.scale,
		outputLocation: args.output,
	});
	console.log(JSON.stringify({ok: true, frames: composition.durationInFrames}));
} catch (err) {
	const message = err && err.message ? err.message : String(err);
	console.log(JSON.stringify({ok: false, error: message, browser_errors: browserErrors.slice(-10)}));
	process.exit(1);
}
