"use strict";

// Anime.js is optional presentation: content remains visible if it cannot load.
(() => {
  const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const active = new Map();
  function enter(targets, stagger = false) {
    if (preference.matches || typeof window.anime !== "function") return;
    const nodes = typeof targets === "string" ? document.querySelectorAll(targets)
      : targets instanceof Element ? [targets] : targets;
    for (const node of nodes) {
      active.get(node)?.pause();
      window.anime.remove(node);
      const animation = window.anime({
        targets: node,
        opacity: [0.65, 1],
        translateY: [6, 0],
        duration: 240,
        delay: stagger ? Math.min(active.size, 5) * 30 : 0,
        easing: "easeOutQuad",
        complete: () => {
          active.delete(node);
          node.style.removeProperty("opacity");
          node.style.removeProperty("transform");
        },
      });
      active.set(node, animation);
    }
  }
  preference.addEventListener("change", () => {
    if (!preference.matches) return;
    for (const [node, animation] of active) {
      animation.pause();
      window.anime.remove(node);
      node.style.removeProperty("opacity");
      node.style.removeProperty("transform");
    }
    active.clear();
  });
  window.dashboardMotion = { enter };
})();
