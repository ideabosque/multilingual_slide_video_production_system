/*
 * GSAP animation runtime for one slide deck. Identical file across every
 * slide in every deck (see .agents/skills/gsap_animation_authoring/SKILL.md
 * "Injection point") - it is a generic *engine* plus a small fixed
 * registry of effect primitives (reveal/accent_line/count_up), not
 * per-template code. The actual templates (title_reveal, feature_callout,
 * ...) are declarative data from templates_config.js
 * (window.__ANIMATION_TEMPLATES__, generated from
 * config/animation_templates.yaml) - per-slide, only the tiny inline
 * `window.__ANIMATION_TEMPLATE__` assignment written before this script
 * differs. Adding or tuning a template is normally a YAML edit in that
 * file, not a change here - see its header comment for the step schema.
 *
 * Element targeting: decks are NOT authored with animation-specific CSS
 * classes (they predate this feature) - `pickEl`/`pickAll` below try, in
 * order: an explicit `.slide-*` class if a deck happens to define one,
 * then a *repeated-sibling-group* heuristic (real decks commonly express
 * card/row/layer grids as N sibling <div>s sharing one class - e.g.
 * `.layer-stack > .layer` - rather than semantic <li>/<p>), then common
 * semantic HTML as a last resort. A template step whose role resolves to
 * nothing simply skips that beat (see runTemplateSteps) rather than
 * throwing, since a missing optional element is not the same failure
 * class as a broken selector (see SKILL.md's self-check item 5).
 */
(function () {
  "use strict";

  // `scope` (everywhere below) is what role resolution searches: the whole
  // `document` for a standalone slide page (Playwright capture), or one
  // slide's root element when several slides share a page (HyperFrames
  // mounts every slide into one document - plan B4's spike).
  function scopeElement(scope) {
    return scope === document ? document.documentElement : scope;
  }

  function readTokens(scope, slideDuration) {
    var cs = getComputedStyle(scopeElement(scope));
    var num = function (name, fallback) {
      var raw = cs.getPropertyValue(name).trim();
      var parsed = parseFloat(raw);
      return isNaN(parsed) ? fallback : parsed;
    };
    return {
      durationFast: num("--ds-motion-duration-fast-ms", 120) / 1000,
      durationBase: num("--ds-motion-duration-base-ms", 160) / 1000,
      durationSlow: num("--ds-motion-duration-slow-ms", 200) / 1000,
      slideEnter: num("--ds-motion-slide-enter-ms", 480) / 1000,
      slideExit: num("--ds-motion-slide-exit-ms", 320) / 1000,
      accentColor: cs.getPropertyValue("--ds-color-accent-signal").trim() || "#D87C2C",
      ease: "power2.out",
      // The slide's on-screen length (narration + pause). Known to frame-
      // seeking engines; a sensible default otherwise. Beat positions and
      // the ambient/exit effects are laid out against it.
      slideDuration: slideDuration > 0 ? slideDuration : 6,
      scope: scope,
    };
  }

  // Tiers are tried in order and the first match wins, so a lower tier
  // (e.g. h3 for the title) only applies when nothing above it exists -
  // decks that already resolve keep resolving to the same element.
  function pickEl(scope, customClass, tagSelector, lastResort) {
    return scope.querySelector(customClass) || scope.querySelector(tagSelector)
      || (lastResort ? scope.querySelector(lastResort) : null);
  }

  // Finds the largest group of >=2 direct siblings that share a class name,
  // searching the whole scope. This is how most real decks express card/row/
  // layer grids (N divs with one repeated class), as opposed to semantic
  // <li>/<p> - see this file's header comment.
  function findRepeatedSiblingGroup(scope) {
    var all = scope === document ? document.querySelectorAll("body *") : scope.querySelectorAll("*");
    var best = null;
    var bestSize = 0;
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var byClass = {};
      for (var j = 0; j < el.children.length; j++) {
        var child = el.children[j];
        var cls = typeof child.className === "string" ? child.className.trim().split(/\s+/)[0] : "";
        if (!cls) continue;
        (byClass[cls] = byClass[cls] || []).push(child);
      }
      for (var key in byClass) {
        if (byClass[key].length >= 2 && byClass[key].length > bestSize) {
          best = byClass[key];
          bestSize = byClass[key].length;
        }
      }
    }
    return best || [];
  }

  function pickAll(scope, customClass, tagSelector) {
    var byClass = scope.querySelectorAll(customClass);
    if (byClass.length) return Array.prototype.slice.call(byClass);
    var repeated = findRepeatedSiblingGroup(scope);
    if (repeated.length) return repeated;
    return Array.prototype.slice.call(scope.querySelectorAll(tagSelector));
  }

  // The element holding the whole slide: what camera moves (drift) and
  // exits act on. HyperFrames slides wrap their body in
  // [data-motion-slide-body] (hyperframes_engine.py); a standalone page
  // uses <body>.
  function slideElement(scope) {
    if (scope === document) return document.body;
    return scope.querySelector("[data-motion-slide-body]") || scope;
  }

  function roleElements(scope) {
    return {
      slide: slideElement(scope),
      // h3 only when the slide has no h1/h2 (card-layout slides headline
      // with h3 - run-20260911-002's slide_010 resolved no title at all).
      title: pickEl(scope, ".slide-title", "h1, h2", "h3"),
      subtitle: pickEl(scope, ".slide-subtitle", "h1 + p, h2 + p, .subtitle"),
      body: pickAll(scope, ".slide-bullets li, .slide-body", "li, p"),
      diagram: pickEl(scope, ".slide-diagram", "svg, .diagram, img"),
      // Common big-number class names real decks use (`.stat-num` on
      // run-20260911-002's slides 5 and 7 resolved no stat, so their
      // stat_highlight template animated nothing).
      stat: pickEl(scope, ".slide-stat, .slide-stat-number",
                   "[data-stat], .stat, .stat-num, .stat-number, .stat-value, .metric-value"),
      cta: pickEl(scope, ".slide-cta", "a.btn, button, .cta"),
      // `.slide-diagram-node` is an explicit opt-in for a deck author who
      // wants to mark specific elements; pickAll's second tier
      // (findRepeatedSiblingGroup) covers the common case with no deck-
      // author effort - most decks express a "diagram" as a grid of N
      // sibling cards, not an <svg>/<img>.
      nodes: pickAll(scope, ".slide-diagram-node", "__no_semantic_fallback__"),
    };
  }

  // ---------- stat text parsing (shared by count_up and role extraction) ----------
  // Parses a leading/embedded numeric value out of an element's text
  // (handles "40%", "3x faster", "$1.2M saved", "99.9%"); null when the
  // text has no number. `decimals` comes from the source text, not the
  // parsed float, so "1.50" keeps two decimals instead of becoming "1.5".
  function statParts(text) {
    var match = /^(\D*)([\d]+(?:\.[\d]+)?)(.*)$/.exec((text || "").trim());
    if (!match) return null;
    return {
      prefix: match[1],
      value: parseFloat(match[2]),
      decimals: (match[2].split(".")[1] || "").length,
      suffix: match[3],
    };
  }

  // ---------- role extraction (B3 #2, `msv slides extract-roles`) ----------
  // Serializes what the role resolution actually resolved on the current
  // DOM - one definition of "what is the title of this slide" for every
  // engine, exposed as `window.__extractRoles()`. Plain DOM reads, no
  // mutation; the text is read from the (already-translated) DOM, so it is
  // localized automatically. Extraction runs against a `seek`-mode
  // injection so the timeline stays paused at 0 and stat/count-up text is
  // read pre-animation.
  window.__extractRoles = function (scope) {
    scope = scope || document;
    var els = roleElements(scope);
    var textOf = function (el) { return el ? (el.textContent || "").trim() : null; };
    var nodes = (els.nodes || []).map(function (el) {
      return {
        text: textOf(el),
        children: Array.prototype.slice.call(el.children).map(textOf),
      };
    });
    var media = [];
    var mediaEls = Array.prototype.slice.call(scope.querySelectorAll("svg, img"));
    for (var mi = 0; mi < mediaEls.length; mi++) {
      var mediaEl = mediaEls[mi];
      media.push({
        type: mediaEl.tagName.toLowerCase(),
        src: mediaEl.tagName.toLowerCase() === "img" ? (mediaEl.getAttribute("src") || "") : "",
      });
    }
    return {
      title: textOf(els.title),
      subtitle: textOf(els.subtitle),
      body: (els.body || []).map(textOf),
      diagram: els.diagram ? { tag: els.diagram.tagName.toLowerCase(), text: textOf(els.diagram) } : null,
      nodes: nodes,
      stat: els.stat ? statParts(textOf(els.stat)) : null,
      cta: textOf(els.cta),
      media: media,
    };
  };

  // ---------- shared decorative effect: drawn accent-line under an element ----------
  // Inserted into normal document flow right after `afterEl` (no absolute
  // positioning/measurement needed), then scaled in from zero width.
  // Non-essential polish: any DOM failure here is swallowed, never allowed
  // to break the timeline itself.
  function drawAccentLine(tl, ds, afterEl, position) {
    if (!afterEl || !afterEl.parentNode) return;
    try {
      var line = document.createElement("div");
      line.setAttribute("data-animation-accent-line", "true");
      line.style.height = "3px";
      line.style.width = "64px";
      line.style.marginTop = "10px";
      line.style.marginBottom = "2px";
      line.style.background = ds.accentColor;
      line.style.transformOrigin = "left center";
      afterEl.insertAdjacentElement("afterend", line);
      tl.from(line, { scaleX: 0, duration: ds.durationSlow, ease: ds.ease }, position);
    } catch (e) {
      // Decorative only - never fail the whole timeline over this.
    }
  }

  // The first text node under `el` that contains a digit - the number to
  // count. Writing only that node (not el.textContent) keeps styled child
  // elements intact, e.g. `60<span class="unit">%</span>`.
  function numberTextNode(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (var node = walker.nextNode(); node; node = walker.nextNode()) {
      if (/\d/.test(node.nodeValue)) return node;
    }
    return null;
  }

  // Splits an element's text into one inline-block span per word (per
  // character for Chinese/Japanese, which don't separate words with
  // spaces), keeping whitespace and child elements, so `words` can animate
  // them individually. Done once per element, at build time - the same
  // DOM every time the timeline is seeked.
  var CJK_RE = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/;
  function splitWords(el) {
    if (el.__motionWords) return el.__motionWords;
    var spans = [];
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var textNodes = [];
    for (var n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeValue.trim()) textNodes.push(n);
    }
    textNodes.forEach(function (node) {
      var text = node.nodeValue;
      var parts = CJK_RE.test(text) ? Array.from(text) : text.split(/(\s+)/);
      var frag = document.createDocumentFragment();
      parts.forEach(function (part) {
        if (!part) return;
        if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
        var span = document.createElement("span");
        span.textContent = part;
        span.style.display = "inline-block";
        span.setAttribute("data-motion-word", "");
        frag.appendChild(span);
        spans.push(span);
      });
      node.parentNode.replaceChild(frag, node);
    });
    el.__motionWords = spans;
    return spans;
  }

  // ---------- shared effect: animate a stat element's number counting up ----------
  // Tweens a counter from 0 to the parsed value (see statParts), preserving
  // the original prefix/suffix text, decimal precision and any styled child
  // elements (only the digits' own text node is rewritten). Falls back to a
  // plain scale-in (no count-up) if no number is found - never leaves the
  // element blank. `params.pop` (playful style) makes the entrance a
  // springy scale-in instead of a fade - one entrance tween either way, so
  // it never stacks a second .from() on the same element.
  function animateCountUp(tl, ds, el, position, step) {
    var p = (step && step.params) || {};
    var textNode = numberTextNode(el);
    var stat = textNode ? statParts(textNode.nodeValue) : null;
    if (!stat) {
      tl.from(el, { opacity: 0, scale: 0.86, duration: ds.durationSlow, ease: "back.out(1.2)" }, position);
      return;
    }
    var prefix = stat.prefix, target = stat.value, suffix = stat.suffix, decimals = stat.decimals;
    // Seek-safety (plan B3's count_up caveat): the text is written by the
    // tweened property's own setter, not an onUpdate callback. GSAP's
    // seek() suppresses callbacks by default, so a callback-driven counter
    // never changes under a frame-seeking renderer; a property setter runs
    // on every render, live or seeked. The value is derived from playhead
    // progress (never accumulated per tick or read from the wall clock),
    // so seeking backwards or jumping ahead shows the right number -
    // asserted mid-tween by tests/test_motion_runtime_seek.py.
    var current = 0;
    var counter = {};
    Object.defineProperty(counter, "val", {
      get: function () { return current; },
      set: function (v) {
        current = v;
        textNode.nodeValue = prefix + v.toFixed(decimals) + suffix;
      },
    });
    if (p.pop) {
      tl.from(el, {
        opacity: 0, scale: p.scale !== undefined ? p.scale : 0.3,
        duration: ds.slideEnter * 1.4, ease: "back.out(2.5)",
      }, position);
    } else {
      tl.from(el, { opacity: 0, duration: ds.durationFast, ease: ds.ease }, position);
    }
    // fromTo renders its start value as soon as it's built (the element is
    // still at opacity 0 then), so t=0 shows the same "0" on first visit as
    // after seeking back - a plain .to() left the source text until the
    // tween first rendered, which made t=0 depend on seek history.
    tl.fromTo(counter, { val: 0 }, {
      val: target, duration: p.pop ? ds.slideEnter * 2.5 : ds.slideEnter, ease: "power2.out", immediateRender: true,
    }, position);
  }

  // ---------- generic template engine ----------
  // A "template" is declarative data from templates_config.js
  // (window.__ANIMATION_TEMPLATES__, generated from
  // config/animation_templates.yaml - see that file's header comment for
  // the step schema) - not JS code. Adding or tuning a template is
  // normally a YAML edit; this engine and the three effect primitives
  // below are the small, fixed surface that YAML can't express (see
  // motion_design_principles SKILL.md and gsap_animation_authoring
  // SKILL.md's "Template config schema").

  var DURATION_TOKENS = {
    fast: "durationFast",
    base: "durationBase",
    slow: "durationSlow",
    slide_enter: "slideEnter",
    slide_exit: "slideExit",
  };

  function resolveDurationToken(ds, token, fallback) {
    if (token == null) return fallback;
    var key = DURATION_TOKENS[token];
    return key ? ds[key] : fallback;
  }

  // A step position may be "beat:<fraction>" - that fraction of the
  // slide's duration, in seconds - so motion can arrive while the narrator
  // is still talking instead of all firing in the first half-second.
  function resolvePosition(position, ds) {
    if (typeof position === "string" && position.indexOf("beat:") === 0) {
      return parseFloat(position.slice(5)) * ds.slideDuration;
    }
    return position;
  }

  function asList(target) {
    return Array.isArray(target) ? target : [target];
  }

  function resolveRole(role, els) {
    var keys = Array.isArray(role) ? role : [role];
    for (var i = 0; i < keys.length; i++) {
      var v = els[keys[i]];
      if (Array.isArray(v)) {
        if (v.length) return v;
      } else if (v) {
        return v;
      }
    }
    // No candidate found - report back an empty list vs. null so callers
    // can tell "role resolves to a list type but it's empty" apart from
    // "role resolves to a single element and it's missing" if ever needed;
    // both are treated as "skip this step" today.
    return Array.isArray(els[keys[0]]) ? [] : null;
  }

  // Effect primitives - the only place actual GSAP tween code lives.
  // Every template step names one of these by `effect`; new *effects*
  // (as opposed to new *templates*) are the rare case that needs a JS
  // change - see gsap_animation_authoring SKILL.md.
  var EFFECTS = {
    reveal: function (tl, ds, target, position, step) {
      var params = step.params || {};
      var vars = {
        opacity: 0,
        duration: resolveDurationToken(ds, step.duration, ds.durationBase),
        ease: step.ease || ds.ease,
      };
      if (params.y !== undefined) vars.y = params.y;
      if (params.x !== undefined) vars.x = params.x;
      if (params.scale !== undefined) vars.scale = params.scale;
      if (params.stagger !== undefined) {
        vars.stagger = typeof params.stagger === "string"
          ? resolveDurationToken(ds, params.stagger, ds.durationFast)
          : params.stagger;
      }
      if (position === undefined || position === null) tl.from(target, vars);
      else tl.from(target, vars, position);
    },
    accent_line: function (tl, ds, target, position) {
      drawAccentLine(tl, ds, target, position);
    },
    count_up: function (tl, ds, target, position, step) {
      animateCountUp(tl, ds, target, position, step);
    },

    // ----- playful style (config/animation_templates_playful.yaml) -----
    // Every effect below is seek-safe: explicit from/to values, finite
    // repeats, no callbacks, no wall clock - each frame is a pure function
    // of timeline time.

    // Springy scale-in with overshoot.
    pop: function (tl, ds, target, position, step) {
      var p = step.params || {};
      var vars = {
        opacity: 0,
        scale: p.scale !== undefined ? p.scale : 0.4,
        duration: resolveDurationToken(ds, step.duration, ds.slideEnter),
        ease: step.ease || "back.out(2.2)",
      };
      if (p.y !== undefined) vars.y = p.y;
      if (p.x !== undefined) vars.x = p.x;
      if (p.rotation !== undefined) vars.rotation = p.rotation;
      if (p.stagger !== undefined) vars.stagger = p.stagger;
      tl.from(target, vars, position);
    },

    // Kinetic text: words (or CJK characters) bounce up one after another.
    words: function (tl, ds, target, position, step) {
      var p = step.params || {};
      var spans = [];
      asList(target).forEach(function (el) { spans = spans.concat(splitWords(el)); });
      if (!spans.length) return;
      tl.from(spans, {
        opacity: 0,
        y: p.y !== undefined ? p.y : 36,
        rotation: p.rotation !== undefined ? p.rotation : 6,
        scale: p.scale !== undefined ? p.scale : 0.9,
        duration: resolveDurationToken(ds, step.duration, ds.slideEnter),
        ease: step.ease || "back.out(2)",
        stagger: p.stagger !== undefined ? p.stagger : 0.05,
      }, position);
    },

    // Items pop in one by one, spread between two fractions of the slide's
    // duration, so a long narration keeps revealing content. The first item
    // never waits longer than `first_max` seconds (default 1.2): on a long
    // slide, 15% can be 7s of empty screen, and the first item often
    // carries the slide's headline.
    beats: function (tl, ds, target, position, step) {
      var p = step.params || {};
      var items = asList(target);
      var first = Math.min((p.from !== undefined ? p.from : 0.12) * ds.slideDuration,
                           p.first_max !== undefined ? p.first_max : 1.2);
      var last = Math.max(first, (p.to !== undefined ? p.to : 0.6) * ds.slideDuration);
      var duration = resolveDurationToken(ds, step.duration, ds.slideEnter);
      items.forEach(function (item, i) {
        var at = items.length > 1 ? first + (last - first) * i / (items.length - 1) : first;
        tl.from(item, {
          opacity: 0,
          scale: p.scale !== undefined ? p.scale : 0.5,
          y: p.y !== undefined ? p.y : 30,
          rotation: p.rotation !== undefined ? (i % 2 ? -p.rotation : p.rotation) : 0,
          duration: duration,
          ease: step.ease || "back.out(2.4)",
        }, at);
      });
    },

    // Gentle ambient bob from `position` to the end of the slide.
    float: function (tl, ds, target, position, step) {
      var p = step.params || {};
      var start = typeof position === "number" ? position : ds.slideEnter + 0.4;
      var half = (p.period !== undefined ? p.period : 3) / 2;
      var repeats = Math.floor((ds.slideDuration - start) / half) - 1;
      if (repeats < 1) return;
      tl.fromTo(target, { y: 0 }, {
        y: -(p.y !== undefined ? p.y : 8), duration: half, ease: "sine.inOut",
        yoyo: true, repeat: repeats, immediateRender: false,
      }, start);
    },

    // Slow camera push-in on the whole slide, for the slide's full length.
    drift: function (tl, ds, target, position, step) {
      var p = step.params || {};
      asList(target).forEach(function (el) { el.style.transformOrigin = "50% 50%"; });
      tl.fromTo(target, { scale: 1 }, {
        scale: p.scale !== undefined ? p.scale : 1.035,
        duration: ds.slideDuration, ease: "none", immediateRender: false,
      }, 0);
    },

    // Quick fade-up just before the cut to the next slide. Opacity and y
    // only, so it never fights drift's scale on the same element.
    exit: function (tl, ds, target, position, step) {
      var p = step.params || {};
      var duration = resolveDurationToken(ds, step.duration, ds.slideExit);
      tl.fromTo(target, { opacity: 1, y: 0 }, {
        opacity: 0, y: p.y !== undefined ? p.y : -18, duration: duration,
        ease: step.ease || "power2.in", immediateRender: false,
      }, Math.max(0, ds.slideDuration - duration));
    },
  };

  // Plays one template's `steps` (from templates_config.js) into `tl`.
  // Effects that bring an element in from a hidden starting state. Two of
  // them on one element break it: GSAP's second .from() records the first
  // one's hidden state as its end value, so the element never appears
  // (e.g. a `subtitle` that is also one of the `body` paragraphs). The
  // first entrance step claims an element; later entrance steps skip it.
  var ENTRANCE_EFFECTS = { reveal: true, count_up: true, pop: true, words: true, beats: true };

  function unclaimed(target, claimed) {
    if (Array.isArray(target)) {
      return target.filter(function (el) { return claimed.indexOf(el) === -1; });
    }
    return claimed.indexOf(target) === -1 ? target : null;
  }

  function runTemplateSteps(tl, ds, els, steps) {
    var ranStepIds = {};
    var anyStepRan = false;
    var claimed = [];
    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      if (step.skip_if_ran && ranStepIds[step.skip_if_ran]) continue;

      var target = resolveRole(step.role, els);
      if (target != null && ENTRANCE_EFFECTS[step.effect]) target = unclaimed(target, claimed);
      var isEmpty = target == null || (Array.isArray(target) && target.length === 0);
      if (isEmpty) continue;
      if (step.min_count && Array.isArray(target) && target.length < step.min_count) continue;
      if (ENTRANCE_EFFECTS[step.effect]) claimed = claimed.concat(asList(target));

      var effect = EFFECTS[step.effect];
      if (!effect) {
        // A config-level typo should fail loudly (console error -> capture
        // step fails the render), not silently skip a beat - see
        // gsap_animation_authoring SKILL.md's self-check.
        throw new Error("Unknown animation effect in templates_config.js: " + step.effect);
      }
      var position = (!anyStepRan && step.position_if_first !== undefined) ? step.position_if_first : step.position;
      effect(tl, ds, target, resolvePosition(position, ds), step);

      if (step.id) ranStepIds[step.id] = true;
      anyStepRan = true;
    }
  }

  function templateSteps(name, templates) {
    templates = templates || window.__ANIMATION_TEMPLATES__ || {};
    return (templates[name] || templates.feature_callout || {}).steps || [];
  }

  // Builds one slide's timeline against `scope` - the single construction
  // path every engine uses, so what a seeking renderer draws is what the
  // live engine plays. Paused unless `opts.paused === false`.
  window.__motionBuildTimeline = function (scope, opts) {
    opts = opts || {};
    var tl = gsap.timeline(opts.paused === false ? undefined : { paused: true });
    runTemplateSteps(tl, readTokens(scope, opts.duration), roleElements(scope),
                     templateSteps(opts.template, opts.templates));
    // Deliberately no .clearProps()/.reverse() - every engine relies on the
    // timeline holding its final state for the rest of the slide (see
    // gsap_animation_authoring SKILL.md).
    return tl;
  };

  // Seek-mode entry point for one slide among several in one page
  // (HyperFrames, plan B4): resolves roles inside `rootEl` only, registers
  // the paused timeline as window.__timelines[slideId] for the renderer to
  // seek, and never touches page visibility.
  window.__motionRunSlide = function (rootEl, opts) {
    opts = opts || {};
    var tl = window.__motionBuildTimeline(rootEl, {
      template: opts.template, templates: opts.templates, duration: opts.duration,
    });
    window.__timelines = window.__timelines || {};
    window.__timelines[opts.slideId || "slide"] = tl;
    return tl;
  };

  // Page-wide auto-run for a standalone slide page (slides/render.py's
  // injection sets window.__ANIMATION_TEMPLATE__). Pages without that
  // global - e.g. a HyperFrames composition calling __motionRunSlide per
  // slide - are left alone.
  function run() {
    if (window.__ANIMATION_TEMPLATE__ === undefined) return;
    var mode = window.__MOTION_MODE__ === "seek" ? "seek" : "live";
    // Live capture with a sentinel (window.__CAPTURE_SENTINEL_MS__, set
    // only by slides/render.py's capture injection) also starts paused:
    // the page shows a solid magenta overlay for that long before the
    // timeline plays, so the recording carries an unambiguous "slide
    // starts here" marker whatever the deck's own background colour is
    // (playwright_engine.py's lead-in detection keys on it).
    var sentinelMs = mode === "live" ? Number(window.__CAPTURE_SENTINEL_MS__ || 0) : 0;
    var tl;
    if (mode === "seek") {
      tl = window.__motionRunSlide(document, {
        slideId: window.__ANIMATION_SLIDE_ID__, template: window.__ANIMATION_TEMPLATE__,
        duration: window.__ANIMATION_SLIDE_DURATION__,
      });
    } else {
      tl = window.__motionBuildTimeline(document, {
        template: window.__ANIMATION_TEMPLATE__, paused: sentinelMs > 0,
        duration: window.__ANIMATION_SLIDE_DURATION__,
      });
    }

    // The page is hidden (see the inline `html{visibility:hidden}` style
    // injected alongside this script) until this point, so the browser's
    // first paint already shows every animated element at its GSAP "from"
    // state - gsap.from()/timeline construction applies those starting
    // values synchronously, before this line runs. Without this, the page
    // would paint once at its normal (post-animation) CSS state, then jump
    // to the animation's start a frame later - a visible white/default
    // flash at the start of every captured clip (confirmed in production
    // output, not just theoretical - see marketing_animation_pipeline_plan.md).
    var reveal = function () {
      document.documentElement.setAttribute("data-motion-revealed", "");
      document.documentElement.style.visibility = "visible";
      if (sentinelMs > 0) tl.play(0);
    };
    if (sentinelMs > 0) {
      // Two frames first so the sentinel is actually painted (and
      // recorded) before the hold starts counting.
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { setTimeout(reveal, sentinelMs); });
      });
    } else {
      reveal();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();