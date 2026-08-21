/*
 * GSAP animation runtime for one slide deck. Identical file across every
 * slide in a deck (see .claude/skills/gsap_animation_authoring/SKILL.md
 * "Injection point") - only the tiny inline `window.__ANIMATION_TEMPLATE__`
 * assignment written before this script differs per slide.
 *
 * Element targeting: decks are NOT authored with animation-specific CSS
 * classes (they predate this feature) - `pickEl`/`pickAll` below try, in
 * order: an explicit `.slide-*` class if a deck happens to define one,
 * then a *repeated-sibling-group* heuristic (real decks commonly express
 * card/row/layer grids as N sibling <div>s sharing one class - e.g.
 * `.layer-stack > .layer` - rather than semantic <li>/<p>), then common
 * semantic HTML as a last resort. A shot template that finds nothing for
 * a given role simply skips that beat (see buildTimeline's per-role
 * guards) rather than throwing, since a missing optional element is not
 * the same failure class as a broken selector (see SKILL.md's self-check
 * item 5).
 */
(function () {
  "use strict";

  function readTokens() {
    var cs = getComputedStyle(document.documentElement);
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
    };
  }

  function pickEl(customClass, tagSelector) {
    return document.querySelector(customClass) || document.querySelector(tagSelector);
  }

  // Finds the largest group of >=2 direct siblings that share a class name,
  // searching the whole body. This is how most real decks express card/row/
  // layer grids (N divs with one repeated class), as opposed to semantic
  // <li>/<p> - see this file's header comment.
  function findRepeatedSiblingGroup() {
    var all = document.querySelectorAll("body *");
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

  function pickAll(customClass, tagSelector) {
    var byClass = document.querySelectorAll(customClass);
    if (byClass.length) return Array.prototype.slice.call(byClass);
    var repeated = findRepeatedSiblingGroup();
    if (repeated.length) return repeated;
    return Array.prototype.slice.call(document.querySelectorAll(tagSelector));
  }

  function roleElements() {
    return {
      title: pickEl(".slide-title", "h1, h2"),
      subtitle: pickEl(".slide-subtitle", "h1 + p, h2 + p, .subtitle"),
      body: pickAll(".slide-bullets li, .slide-body", "li, p"),
      diagram: pickEl(".slide-diagram", "svg, .diagram, img"),
      stat: pickEl(".slide-stat, .slide-stat-number", "[data-stat], .stat"),
      cta: pickEl(".slide-cta", "a.btn, button, .cta"),
    };
  }

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

  // ---------- shared effect: animate a stat element's number counting up ----------
  // Parses a leading/embedded numeric value out of the element's text
  // (handles "40%", "3x faster", "$1.2M saved", "99.9%") and tweens a
  // counter from 0 to that value, preserving the original prefix/suffix
  // text and decimal precision. Falls back to a plain scale-in (no
  // count-up) if no number is found - never leaves the element blank.
  function animateCountUp(tl, ds, el, position) {
    var match = /^(\D*)([\d]+(?:\.[\d]+)?)(.*)$/.exec((el.textContent || "").trim());
    if (!match) {
      tl.from(el, { opacity: 0, scale: 0.86, duration: ds.durationSlow, ease: "back.out(1.2)" }, position);
      return;
    }
    var prefix = match[1], target = parseFloat(match[2]), suffix = match[3];
    var decimals = (match[2].split(".")[1] || "").length;
    var counter = { val: 0 };
    tl.from(el, { opacity: 0, duration: ds.durationFast, ease: ds.ease }, position);
    tl.to(counter, {
      val: target,
      duration: ds.slideEnter,
      ease: "power2.out",
      onUpdate: function () {
        el.textContent = prefix + counter.val.toFixed(decimals) + suffix;
      },
    }, position);
  }

  // ---------- shot templates (see motion_design_principles SKILL.md) ----------

  function titleReveal(tl, ds, els) {
    if (els.title) {
      tl.from(els.title, { opacity: 0, y: 24, duration: ds.slideEnter, ease: ds.ease });
      drawAccentLine(tl, ds, els.title, ">-0.1");
    }
    if (els.subtitle) {
      tl.from(els.subtitle, { opacity: 0, y: 16, duration: ds.durationSlow, ease: ds.ease }, ">-0.1");
    }
  }

  function featureCallout(tl, ds, els) {
    if (els.title) {
      tl.from(els.title, { opacity: 0, y: 20, scale: 0.98, duration: ds.durationSlow, ease: ds.ease });
      drawAccentLine(tl, ds, els.title, ">-0.08");
    }
    if (els.subtitle) {
      tl.from(els.subtitle, { opacity: 0, y: 14, duration: ds.durationBase, ease: ds.ease }, ">-0.05");
    }
    if (els.body.length) {
      tl.from(els.body, {
        opacity: 0, y: 16, x: -10, duration: ds.durationBase, ease: ds.ease,
        stagger: ds.durationFast,
      }, els.title ? ">-0.05" : 0);
    }
  }

  function statHighlight(tl, ds, els) {
    var focal = els.stat || els.title;
    if (focal) {
      animateCountUp(tl, ds, focal, 0);
    }
    if (els.subtitle) {
      tl.from(els.subtitle, { opacity: 0, y: 12, duration: ds.durationBase, ease: ds.ease }, ">-0.05");
    }
  }

  function diagramBuild(tl, ds, els) {
    if (els.title) {
      tl.from(els.title, { opacity: 0, y: 18, duration: ds.durationSlow, ease: ds.ease });
      drawAccentLine(tl, ds, els.title, ">-0.08");
    }
    // `.slide-diagram-node` is an explicit opt-in for a deck author who
    // wants to mark specific elements; pickAll's second tier
    // (findRepeatedSiblingGroup) covers the common case with no
    // deck-author effort - most decks express a "diagram" as a grid of N
    // sibling cards, not an <svg>/<img>, so a staggered per-card reveal is
    // usually the right "build" effect even without a dedicated diagram
    // element.
    var nodes = pickAll(".slide-diagram-node", "__no_semantic_fallback__");
    if (nodes.length > 1) {
      tl.from(nodes, {
        opacity: 0, y: 14, scale: 0.96, duration: ds.durationBase, ease: ds.ease,
        stagger: ds.durationFast,
      }, els.title ? ">-0.1" : 0);
    } else if (els.diagram) {
      tl.from(els.diagram, { opacity: 0, scale: 0.96, duration: ds.slideEnter, ease: ds.ease }, els.title ? ">-0.1" : 0);
    }
  }

  function closing(tl, ds, els) {
    if (els.title) {
      tl.from(els.title, { opacity: 0, y: 20, duration: ds.durationSlow, ease: ds.ease });
      drawAccentLine(tl, ds, els.title, ">-0.08");
    }
    if (els.cta) {
      tl.from(els.cta, { opacity: 0, y: 12, scale: 0.94, duration: ds.durationBase, ease: "back.out(1.4)" }, ">-0.05");
    }
  }

  var TEMPLATES = {
    title_reveal: titleReveal,
    feature_callout: featureCallout,
    stat_highlight: statHighlight,
    diagram_build: diagramBuild,
    closing: closing,
  };

  function run() {
    var name = window.__ANIMATION_TEMPLATE__ || "feature_callout";
    var build = TEMPLATES[name] || TEMPLATES.feature_callout;
    var ds = readTokens();
    var els = roleElements();
    var tl = gsap.timeline();
    build(tl, ds, els);
    // Deliberately no .clearProps()/.reverse() - the capture step relies on
    // the timeline holding its final state for the rest of the recording
    // (see gsap_animation_authoring SKILL.md).

    // The page is hidden (see the inline `html{visibility:hidden}` style
    // injected alongside this script) until this point, so the browser's
    // first paint already shows every animated element at its GSAP "from"
    // state - gsap.from()/timeline construction applies those starting
    // values synchronously, before this line runs. Without this, the page
    // would paint once at its normal (post-animation) CSS state, then jump
    // to the animation's start a frame later - a visible white/default
    // flash at the start of every captured clip (confirmed in production
    // output, not just theoretical - see marketing_animation_pipeline_plan.md).
    document.documentElement.style.visibility = "visible";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
