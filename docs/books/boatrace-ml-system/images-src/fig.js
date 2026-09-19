// 図版共通ヘルパー。箱を絶対配置し、矢印を SVG レイヤーに描く。
// Fig.render(root, {w, h, boxes:[...], groups:[...], arrows:[...], notes:[...]})
const Fig = (() => {
  const boxes = {};
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = { navy: "#2B4C9B", red: "#E5002D", gray: "#6B7280", dark: "#374151", black: "#111827" };

  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function div(cls, style, html, parent) {
    const d = document.createElement("div");
    d.className = cls;
    Object.assign(d.style, style);
    if (html != null) d.innerHTML = html;
    parent.appendChild(d);
    return d;
  }
  function anchor(ref) {
    // ref: [id, side, frac] または [x, y]
    if (typeof ref[0] === "number") return { x: ref[0], y: ref[1] };
    const [id, side = "r", frac = 0.5] = ref;
    const b = boxes[id];
    if (!b) throw new Error("unknown box " + id);
    switch (side) {
      case "l": return { x: b.x, y: b.y + b.h * frac };
      case "r": return { x: b.x + b.w, y: b.y + b.h * frac };
      case "t": return { x: b.x + b.w * frac, y: b.y };
      case "b": return { x: b.x + b.w * frac, y: b.y + b.h };
      case "c": return { x: b.x + b.w / 2, y: b.y + b.h / 2 };
    }
  }
  function route(p, q, mode, mid) {
    // 折れ線の頂点列を返す
    if (mode === "h") return [p, { x: q.x, y: p.y }, q];         // 横→縦
    if (mode === "v") return [p, { x: p.x, y: q.y }, q];         // 縦→横
    if (mode === "hvh") { const mx = mid ?? (p.x + q.x) / 2; return [p, { x: mx, y: p.y }, { x: mx, y: q.y }, q]; }
    if (mode === "vhv") { const my = mid ?? (p.y + q.y) / 2; return [p, { x: p.x, y: my }, { x: q.x, y: my }, q]; }
    return [p, q];
  }
  function pathD(pts, r = 10) {
    // 角を丸めた折れ線
    if (pts.length < 3) return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`;
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i - 1], b = pts[i], c = pts[i + 1];
      const d1 = Math.hypot(b.x - a.x, b.y - a.y), d2 = Math.hypot(c.x - b.x, c.y - b.y);
      const rr = Math.min(r, d1 / 2, d2 / 2);
      const p1 = { x: b.x - (b.x - a.x) / d1 * rr, y: b.y - (b.y - a.y) / d1 * rr };
      const p2 = { x: b.x + (c.x - b.x) / d2 * rr, y: b.y + (c.y - b.y) / d2 * rr };
      d += ` L${p1.x},${p1.y} Q${b.x},${b.y} ${p2.x},${p2.y}`;
    }
    const last = pts[pts.length - 1];
    d += ` L${last.x},${last.y}`;
    return d;
  }
  function midpoint(pts, t = 0.5) {
    const segs = []; let total = 0;
    for (let i = 0; i < pts.length - 1; i++) { const L = Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y); segs.push(L); total += L; }
    let target = total * t;
    for (let i = 0; i < segs.length; i++) {
      if (target <= segs[i] || i === segs.length - 1) { const f = segs[i] ? target / segs[i] : 0; return { x: pts[i].x + (pts[i + 1].x - pts[i].x) * f, y: pts[i].y + (pts[i + 1].y - pts[i].y) * f }; }
      target -= segs[i];
    }
  }
  function render(root, spec) {
    root.style.width = spec.w + "px"; root.style.height = spec.h + "px";
    for (const g of spec.groups || []) {
      const d = div("group " + (g.cls || ""), { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" }, "", root);
      if (g.label) div("gl" + (g.labelIn ? " in" : ""), g.labelStyle || {}, g.label, d);
      boxes[g.id || g.label] = g;
    }
    const svg = el("svg", { class: "layer", width: spec.w, height: spec.h, viewBox: `0 0 ${spec.w} ${spec.h}` }, root);
    const defs = el("defs", {}, svg);
    for (const [name, col] of Object.entries(COLORS)) {
      const m = el("marker", { id: "arr-" + name, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0,0 L10,5 L0,10 z", fill: col }, m);
    }
    for (const b of spec.boxes || []) {
      boxes[b.id] = b;
      const html = (b.title ? `<div class="t">${b.title}</div>` : "") + (b.html || "") + (b.sub ? `<div class="s">${b.sub}</div>` : "");
      const d = div("box " + (b.cls || ""), { left: b.x + "px", top: b.y + "px", width: b.w + "px", height: b.h + "px" }, html, root);
      if (b.style) Object.assign(d.style, b.style);
    }
    for (const a of spec.arrows || []) {
      const p = anchor(a.from), q = anchor(a.to);
      const pts = a.points ? a.points.map(pt => ({ x: pt[0], y: pt[1] })) : route(p, q, a.route, a.mid);
      const col = COLORS[a.color || "dark"];
      const attrs = { d: pathD(pts, a.r), fill: "none", stroke: col, "stroke-width": a.width || 2.5 };
      if (a.dashed) attrs["stroke-dasharray"] = "8 6";
      if (a.opacity != null) attrs["stroke-opacity"] = a.opacity;
      if (!a.noHead) attrs["marker-end"] = `url(#arr-${a.color || "dark"})`;
      if (a.startHead) attrs["marker-start"] = `url(#arr-${a.color || "dark"})`;
      el("path", attrs, svg);
      if (a.label) {
        const m = midpoint(pts, a.t ?? 0.5);
        div("lbl " + (a.labelCls || ""), { left: (m.x + (a.dx || 0)) + "px", top: (m.y + (a.dy || 0)) + "px" }, a.label, root);
      }
    }
    for (const n of spec.notes || []) {
      const d = div("note " + (n.cls || ""), { left: n.x + "px", top: n.y + "px", width: n.w ? n.w + "px" : "auto" }, n.html, root);
      if (n.style) Object.assign(d.style, n.style);
    }
    for (const l of spec.lines || []) {
      const attrs = { x1: l.x1, y1: l.y1, x2: l.x2, y2: l.y2, stroke: COLORS[l.color || "dark"], "stroke-width": l.width || 2 };
      if (l.dashed) attrs["stroke-dasharray"] = "8 6";
      if (l.opacity != null) attrs["stroke-opacity"] = l.opacity;
      el("line", attrs, svg);
    }
    return svg;
  }
  return { render, COLORS, el, anchor };
})();
