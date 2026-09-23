// maxurl_runner.js — run qsniyg/maxurl ("Image Max URL", Apache-2.0) headless under quickjs-ng.
//
//   qjs --std maxurl_runner.js [urls.json] [--page PAGE_URL] [--detail] [--lib PATH] [--timing]
//
// Input : JSON array of image URLs, from the file argument or stdin.
// Output: one JSON object on stdout, {input_url: [candidate, ...]}, best first.
//         Only candidates that differ from the input are listed; [] = maxurl has nothing better.
//         Dropped: bad / fake / problems.smaller / problems.watermark (plus maxurl's own default
//         exclusions possibly_different / possibly_broken), page links, videos, non-http(s) URLs.
//         likely_broken candidates are kept but moved to the end.
// --detail: each candidate becomes {url, headers?, likely_broken?, is_original?, bad_if?} so the
//         caller can see which ones need a Referer or carry a placeholder check.
// --page : the page the images came from (maxurl's host_url; a few rules look at it).
// --lib  : path to userscript_smaller.user.js (default: next to this file).
//
// Offline by design: maxurl runs in its Node mode with do_request = null and cb = null, which is
// the same state the userscript is in when "Rules using API calls" is switched off. require("http")
// and require("https") are stubbed to throw at once, so no rule can reach the network.
// Exit code 0 = ran (even if some URLs failed; they map to []), 2 = maxurl could not be loaded.

(function () {
	var t_start = Date.now();
	var args = scriptArgs.slice(1);
	var in_path = null, page_url = null, detail = false, lib_path = null, timing = false;
	for (var i = 0; i < args.length; i++) {
		var a = args[i];
		if (a === "--detail") detail = true;
		else if (a === "--timing") timing = true;
		else if (a === "--page") page_url = args[++i] || null;
		else if (a === "--lib") lib_path = args[++i] || null;
		else in_path = a;
	}
	var here = scriptArgs[0].replace(/[^/]*$/, "") || "./";
	if (!lib_path) lib_path = here + "userscript_smaller.user.js";

	var DEBUG = !!std.getenv("MAXURL_DEBUG");

	function emit(obj, code) {
		std.out.puts(JSON.stringify(obj));
		std.out.puts("\n");
		std.out.flush();
		// maxurl's URL cache arms 1-hour expiry timers; exit explicitly so nothing lingers.
		std.exit(code);
	}

	// ---------- shims (must exist as globals before maxurl is evaluated) ----------

	function fmt(x) {
		if (typeof x === "string") return x;
		if (x instanceof Error) return String(x) + (x.stack ? "\n" + x.stack : "");
		try { return JSON.stringify(x); } catch (e) { return String(x); }
	}
	function to_stderr() {
		if (!DEBUG) return;
		var parts = [];
		for (var i = 0; i < arguments.length; i++) parts.push(fmt(arguments[i]));
		std.err.puts("[maxurl] " + parts.join(" ") + "\n");
	}
	var noop = function () { };
	// stdout carries only our JSON; all of maxurl's logging goes to stderr (and only with MAXURL_DEBUG=1).
	globalThis.console = {
		log: to_stderr, info: to_stderr, warn: to_stderr, error: to_stderr, debug: to_stderr,
		trace: to_stderr, dir: to_stderr, table: to_stderr, group: noop, groupEnd: noop,
		time: noop, timeEnd: noop, assert: noop
	};

	// Timers never fire: the synchronous rule path does not need them, and firing maxurl's
	// cache-expiry timers would only keep the process alive.
	var timer_seq = 0;
	function FakeTimer() { this.id = ++timer_seq; }
	FakeTimer.prototype.unref = function () { return this; };
	FakeTimer.prototype.ref = function () { return this; };
	FakeTimer.prototype.hasRef = function () { return false; };
	globalThis.setTimeout = function () { return new FakeTimer(); };
	globalThis.setInterval = globalThis.setTimeout;
	globalThis.clearTimeout = noop;
	globalThis.clearInterval = noop;

	// Minimal Buffer: maxurl's Node mode only uses it for base64 (from(s,'base64').toString('binary')
	// and from(s).toString('base64')).
	var B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
	var B64_REV = {};
	for (var bi = 0; bi < 64; bi++) B64_REV[B64.charAt(bi)] = bi;
	B64_REV["-"] = 62; B64_REV["_"] = 63; // Node accepts the URL-safe alphabet too
	function utf8_bytes(s) {
		var out = [];
		for (var i = 0; i < s.length; i++) {
			var c = s.charCodeAt(i);
			if (c >= 0xd800 && c < 0xdc00 && i + 1 < s.length) {
				var d = s.charCodeAt(i + 1);
				if (d >= 0xdc00 && d < 0xe000) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
			}
			if (c < 0x80) out.push(c);
			else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
			else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
			else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
		}
		return out;
	}
	function utf8_decode(bytes) {
		var s = "";
		for (var i = 0; i < bytes.length;) {
			var c = bytes[i++];
			if (c < 0x80) { s += String.fromCharCode(c); continue; }
			var n = c >= 0xf0 ? 3 : c >= 0xe0 ? 2 : c >= 0xc0 ? 1 : 0;
			var cp = n === 3 ? c & 7 : n === 2 ? c & 15 : c & 31;
			if (n === 0) { s += "�"; continue; }
			for (var k = 0; k < n && i < bytes.length; k++) cp = (cp << 6) | (bytes[i++] & 63);
			s += String.fromCodePoint(cp);
		}
		return s;
	}
	function FakeBuffer(bytes) { this.bytes = bytes; this.length = bytes.length; }
	FakeBuffer.prototype.toString = function (enc) {
		var b = this.bytes, s = "", i;
		enc = (enc || "utf8").toLowerCase();
		if (enc === "binary" || enc === "latin1") {
			for (i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
			return s;
		}
		if (enc === "hex") {
			for (i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
			return s;
		}
		if (enc === "base64") {
			for (i = 0; i < b.length; i += 3) {
				var n = (b[i] << 16) | ((b[i + 1] || 0) << 8) | (b[i + 2] || 0);
				s += B64.charAt(n >> 18) + B64.charAt((n >> 12) & 63) +
					(i + 1 < b.length ? B64.charAt((n >> 6) & 63) : "=") +
					(i + 2 < b.length ? B64.charAt(n & 63) : "=");
			}
			return s;
		}
		return utf8_decode(b);
	};
	globalThis.Buffer = {
		from: function (x, enc) {
			if (x instanceof FakeBuffer) return new FakeBuffer(x.bytes.slice());
			if (typeof x !== "string") return new FakeBuffer(Array.prototype.slice.call(x || []));
			enc = (enc || "utf8").toLowerCase();
			var out = [], i;
			if (enc === "base64" || enc === "base64url") {
				var acc = 0, bits = 0;
				for (i = 0; i < x.length; i++) {
					var v = B64_REV[x.charAt(i)];
					if (v === undefined) continue; // skip padding / whitespace like Node does
					acc = (acc << 6) | v; bits += 6;
					if (bits >= 8) { bits -= 8; out.push((acc >> bits) & 255); }
				}
				return new FakeBuffer(out);
			}
			if (enc === "binary" || enc === "latin1") {
				for (i = 0; i < x.length; i++) out.push(x.charCodeAt(i) & 255);
				return new FakeBuffer(out);
			}
			if (enc === "hex") {
				for (i = 0; i + 1 < x.length; i += 2) out.push(parseInt(x.substr(i, 2), 16));
				return new FakeBuffer(out);
			}
			return new FakeBuffer(utf8_bytes(x));
		},
		concat: function (list) {
			var out = [];
			for (var i = 0; i < list.length; i++) out = out.concat(list[i].bytes);
			return new FakeBuffer(out);
		},
		isBuffer: function (x) { return x instanceof FakeBuffer; }
	};

	// CommonJS surface that makes maxurl pick its Node mode (module.exports set, no window/document).
	var offline = function () { throw new Error("maxurl_runner: network access is disabled"); };
	globalThis.module = { exports: {} };
	globalThis.exports = globalThis.module.exports;
	globalThis.require = function (name) {
		if (name === "http" || name === "https") return { request: offline, get: offline };
		var e = new Error("Cannot find module '" + name + "' (maxurl_runner)");
		e.code = "MODULE_NOT_FOUND";
		throw e;
	};
	globalThis.require.main = null; // keeps maxurl from running its own CLI (do_node_main)
	// quickjs-ng's navigator has no .language; maxurl reads it to pick its UI language.
	try {
		if (typeof navigator === "object" && navigator && !navigator.language)
			Object.defineProperty(navigator, "language", { value: "en-US", configurable: true });
	} catch (e) { }

	// ---------- load maxurl ----------

	var bigimage = null;
	try {
		var src = std.loadFile(lib_path);
		if (!src) throw new Error("cannot read " + lib_path);
		std.evalScript(src);
		bigimage = globalThis.module.exports;
	} catch (e) {
		to_stderr("load failed:", String(e), e && e.stack);
	}
	if (typeof bigimage !== "function") {
		std.err.puts("maxurl_runner: failed to load " + lib_path + "\n");
		emit({}, 2);
	}
	var t_loaded = Date.now();

	// ---------- read input ----------

	var urls;
	try {
		var raw = in_path ? std.loadFile(in_path) : std.in.readAsString();
		urls = JSON.parse(raw || "[]");
		if (!Array.isArray(urls)) urls = [];
	} catch (e) {
		std.err.puts("maxurl_runner: input is not a JSON array\n");
		urls = [];
	}

	// ---------- run ----------

	function is_true(v) { return !!v && v !== "false"; }

	function candidates_for(input) {
		var res = bigimage(input, {
			fill_object: true,
			do_request: null,          // offline: API-call rules fall back to their static rewrite
			cb: null,                  // synchronous
			host_url: page_url,
			allow_thirdparty: false,   // never route through third-party proxies
			allow_thirdparty_libs: false,
			allow_thirdparty_code: false
		});
		if (!res) return [];
		if (!Array.isArray(res)) res = [res];
		var good = [], broken = [], seen = {};
		seen[input] = true;
		for (var i = 0; i < res.length; i++) {
			var obj = res[i];
			if (typeof obj === "string") obj = { url: obj };
			if (!obj || typeof obj !== "object") continue;
			if (is_true(obj.bad) || is_true(obj.fake) || obj.is_pagelink || obj.waiting) continue;
			var pr = obj.problems || {};
			if (pr.smaller || pr.watermark || pr.possibly_different || pr.possibly_broken) continue;
			if (obj.media_info && obj.media_info.type && obj.media_info.type !== "image") continue;
			if (obj.video) continue;
			var list = Array.isArray(obj.url) ? obj.url : [obj.url];
			for (var j = 0; j < list.length; j++) {
				var u = list[j];
				if (typeof u !== "string" || !/^https?:\/\//i.test(u) || seen[u]) continue;
				seen[u] = true;
				var item = u;
				if (detail) {
					item = { url: u };
					var h = obj.headers || {};
					if (Object.keys(h).length) item.headers = h;
					if (obj.likely_broken) item.likely_broken = true;
					if (obj.is_original) item.is_original = true;
					if (obj.bad_if && obj.bad_if.length) item.bad_if = obj.bad_if;
				}
				(obj.likely_broken ? broken : good).push(item);
			}
		}
		return good.concat(broken);
	}

	var out = {}, per = [];
	for (var k = 0; k < urls.length; k++) {
		var u = urls[k];
		if (typeof u !== "string" || Object.prototype.hasOwnProperty.call(out, u)) continue;
		var t0 = Date.now();
		try {
			out[u] = candidates_for(u);
		} catch (e) {
			to_stderr("rule error for", u, String(e));
			out[u] = [];
		}
		per.push(Date.now() - t0);
	}

	if (timing) {
		var total = per.reduce(function (a, b) { return a + b; }, 0);
		std.err.puts(JSON.stringify({
			load_ms: t_loaded - t_start, urls: per.length, run_ms: total,
			avg_ms: per.length ? +(total / per.length).toFixed(2) : 0,
			max_ms: per.length ? Math.max.apply(null, per) : 0
		}) + "\n");
	}
	emit(out, 0);
})();
