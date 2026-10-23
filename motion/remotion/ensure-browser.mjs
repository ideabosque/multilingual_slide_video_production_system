// Downloads Remotion's pinned chrome-headless-shell into
// motion/node_modules/.remotion. Run by `msv motion install` after `npm ci`,
// so renders never download anything (plan B3 #3). Prints one JSON line.
import {ensureBrowser} from '@remotion/renderer';

try {
	const status = await ensureBrowser({logLevel: 'error'});
	console.log(JSON.stringify({ok: true, status}));
} catch (err) {
	console.log(JSON.stringify({ok: false, error: err && err.message ? err.message : String(err)}));
	process.exit(1);
}
