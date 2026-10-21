/* holdline judge check: the maths of holdline.judge.calibrate, in the browser.
 *
 * Point estimates (agreement, kappa, false-pass rate, bias, groups, sign reversal) match the Python
 * package exactly. The kappa interval and the held-out threshold split use a seeded random stream of
 * their own, so they agree with the Python numbers within sampling error, not digit for digit.
 * Works in a browser (window.HoldlineJudge) and in Node (module.exports), for the parity test.
 */
(function (root) {
  "use strict";

  var TRUE = ["pass", "passed", "yes", "y", "true", "1", "good", "correct"];
  var FALSE = ["fail", "failed", "no", "n", "false", "0", "bad", "incorrect"];

  function asBool(v) {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v >= 0.5;
    var s = String(v == null ? "" : v).trim().toLowerCase();
    if (TRUE.indexOf(s) >= 0) return true;
    if (FALSE.indexOf(s) >= 0) return false;
    var f = Number(s);
    if (s !== "" && !isNaN(f)) return f >= 0.5;
    throw new Error("cannot read " + JSON.stringify(v) + " as pass or fail");
  }

  function rng(seed) { // mulberry32
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function kappa(a, b, labels) {
    var n = a.length;
    if (n === 0) return NaN;
    labels = labels || uniq(a.concat(b));
    var po = 0, i;
    for (i = 0; i < n; i++) if (a[i] === b[i]) po++;
    po /= n;
    var pe = 0;
    labels.forEach(function (l) {
      var ca = 0, cb = 0;
      for (var j = 0; j < n; j++) { if (a[j] === l) ca++; if (b[j] === l) cb++; }
      pe += (ca / n) * (cb / n);
    });
    if (pe >= 1) return po === 1 ? 1 : 0;
    return (po - pe) / (1 - pe);
  }

  function uniq(xs) {
    var seen = [], i;
    for (i = 0; i < xs.length; i++) if (seen.indexOf(xs[i]) < 0) seen.push(xs[i]);
    return seen.sort(function (x, y) { return String(x) < String(y) ? -1 : String(x) > String(y) ? 1 : 0; });
  }

  function kappaCI(a, b, iters, seed) {
    iters = iters || 2000;
    var k = kappa(a, b), n = a.length;
    if (n < 2) return [k, NaN, NaN];
    var labels = uniq(a.concat(b)), r = rng(seed || 0), ks = [], it, j, ia, ib;
    for (it = 0; it < iters; it++) {
      ia = []; ib = [];
      for (j = 0; j < n; j++) { var x = Math.floor(r() * n); ia.push(a[x]); ib.push(b[x]); }
      ks.push(kappa(ia, ib, labels));
    }
    ks.sort(function (x, y) { return x - y; });
    return [k, ks[Math.floor(0.025 * iters)], ks[Math.min(iters - 1, Math.ceil(0.975 * iters) - 1)]];
  }

  function band(k) {
    if (k !== k) return "undefined";
    var bands = [[0, "poor"], [0.2, "slight"], [0.4, "fair"], [0.6, "moderate"], [0.8, "substantial"]];
    for (var i = 0; i < bands.length; i++) if (k <= bands[i][0]) return bands[i][1];
    return "almost perfect";
  }

  function round(v, d) { if (v == null || v !== v) return null; var m = Math.pow(10, d); return Math.round(v * m) / m; }

  function block(human, judge, withCI) {
    var n = human.length, tp = 0, tn = 0, fp = 0, fn = 0, sh = 0, sj = 0, i;
    for (i = 0; i < n; i++) {
      var h = human[i], j = judge[i];
      if (h && j) tp++; else if (!h && !j) tn++; else if (!h && j) fp++; else fn++;
      if (h) sh++; if (j) sj++;
    }
    var ci = withCI ? kappaCI(human, judge) : [kappa(human, judge), null, null];
    var neg = tn + fp, pos = tp + fn;
    return {
      n: n,
      agreement: n ? round((tp + tn) / n, 4) : null,
      kappa: round(ci[0], 4),
      kappa_ci: ci[1] == null || ci[1] !== ci[1] ? null : [round(ci[1], 4), round(ci[2], 4)],
      kappa_band: band(ci[0]),
      confusion: { tp: tp, tn: tn, fp: fp, fn: fn },
      bias: n ? round((sj - sh) / n, 4) : null,
      false_pass_rate: neg ? round(fp / neg, 4) : null,
      false_fail_rate: pos ? round(fn / pos, 4) : null
    };
  }

  function tuneThreshold(scores, human, seed) {
    var idx = scores.map(function (_, i) { return i; }), r = rng(seed || 0), i;
    for (i = idx.length - 1; i > 0; i--) { var j = Math.floor(r() * (i + 1)); var t = idx[i]; idx[i] = idx[j]; idx[j] = t; }
    var cut = Math.floor(idx.length / 2), fit = idx.slice(0, cut), held = idx.slice(cut);
    var cands = uniq(scores).map(Number).sort(function (x, y) { return x - y; });
    var bestT = 0.5, bestK = -2;
    cands.forEach(function (t) {
      var k = kappa(fit.map(function (i) { return human[i]; }), fit.map(function (i) { return scores[i] >= t; }), [true, false]);
      if (k === k && k > bestK) { bestT = t; bestK = k; }
    });
    var hk = kappa(held.map(function (i) { return human[i]; }), held.map(function (i) { return scores[i] >= bestT; }), [true, false]);
    return { threshold: bestT, kappa_fit_half: round(bestK, 4), kappa_held_out_half: round(hk, 4),
             n_fit: fit.length, n_held_out: held.length };
  }

  /* items: [{human, judge, group?, judge_score?}] (values already picked from the user's columns) */
  function calibrate(items, opts) {
    opts = opts || {};
    var minKappa = opts.minKappa != null ? opts.minKappa : 0.6;
    var maxFalsePass = opts.maxFalsePass != null ? opts.maxFalsePass : 0.10;
    var minN = opts.minN != null ? opts.minN : 30;
    var minGroupN = 5, minBias = 0.05;
    var human = items.map(function (it) { return asBool(it.human); });
    var judge = items.map(function (it) { return asBool(it.judge); });
    var rep = { overall: block(human, judge, true) };

    var groups = {}, order = [];
    items.forEach(function (it, i) {
      if (it.group == null || it.group === "") return;
      var g = String(it.group);
      if (!groups[g]) { groups[g] = [[], []]; order.push(g); }
      groups[g][0].push(human[i]); groups[g][1].push(judge[i]);
    });
    rep.groups = {};
    order.sort().forEach(function (g) { rep.groups[g] = block(groups[g][0], groups[g][1], false); });

    var lenient = [], harsh = [];
    Object.keys(rep.groups).forEach(function (g) {
      var b = rep.groups[g];
      if (b.n >= minGroupN && b.bias != null && Math.abs(b.bias) >= minBias) (b.bias > 0 ? lenient : harsh).push(g);
    });
    rep.sign_reversal = lenient.length > 0 && harsh.length > 0;
    rep.lenient_groups = lenient.sort(); rep.harsh_groups = harsh.sort();

    var hasScores = items.length >= 10 && items.every(function (it) { return it.judge_score != null && it.judge_score !== "" && !isNaN(Number(it.judge_score)); });
    if (hasScores) rep.threshold = tuneThreshold(items.map(function (it) { return Number(it.judge_score); }), human);

    var o = rep.overall, reasons = [];
    if (o.n < minN) reasons.push("only " + o.n + " labelled items (need " + minN + ")");
    if (o.kappa_ci == null || o.kappa_ci[0] < minKappa)
      reasons.push("kappa lower bound " + (o.kappa_ci == null ? "n/a" : o.kappa_ci[0]) + " < " + minKappa);
    if (o.false_pass_rate != null && o.false_pass_rate > maxFalsePass)
      reasons.push("false-pass rate " + o.false_pass_rate + " > " + maxFalsePass + " (judge passes outputs humans fail)");
    if (rep.sign_reversal)
      reasons.push("bias changes sign across groups: lenient on " + rep.lenient_groups.join(", ") + ", harsh on " + rep.harsh_groups.join(", "));
    rep.fit_to_gate = reasons.length === 0;
    rep.reasons = reasons;
    rep.thresholds = { min_kappa: minKappa, max_false_pass: maxFalsePass, min_n: minN };
    return rep;
  }

  /* -- reading files ------------------------------------------------------------------------- */
  function parseCSV(text) {
    var delim = (text.split("\n")[0].match(/\t/g) || []).length > (text.split("\n")[0].match(/,/g) || []).length ? "\t" : ",";
    var rows = [], row = [], field = "", q = false, i, c;
    for (i = 0; i < text.length; i++) {
      c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
        else field += c;
      } else if (c === '"') q = true;
      else if (c === delim) { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = "";
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = [];
      } else field += c;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    if (!rows.length) return [];
    var head = rows[0].map(function (h) { return h.trim(); });
    return rows.slice(1).map(function (r) { var o = {}; head.forEach(function (h, k) { o[h] = r[k] == null ? "" : r[k]; }); return o; });
  }

  function parse(text) {
    var t = text.replace(/^﻿/, "").trim();
    if (!t) return [];
    if (t[0] === "[" || t[0] === "{") {
      try {
        var d = JSON.parse(t);
        if (Array.isArray(d)) return d;
        var keys = ["labels", "items", "results", "rows", "data"];
        for (var i = 0; i < keys.length; i++) if (Array.isArray(d[keys[i]])) return d[keys[i]];
      } catch (e) {
        // not a single JSON document: fall through to JSON lines
      }
      var lines = t.split(/\r?\n/).filter(function (l) { return l.trim(); });
      return lines.map(function (l, n) {
        try { return JSON.parse(l); } catch (e) { throw new Error("line " + (n + 1) + " is not valid JSON"); }
      });
    }
    return parseCSV(t);
  }

  var GUESS = {
    human: ["human", "human_label", "label", "gold", "reference", "expected", "human_verdict", "annotator"],
    judge: ["judge", "judge_label", "judge_verdict", "llm", "llm_judge", "model", "prediction", "predicted", "grader"],
    group: ["group", "difficulty", "band", "category", "type", "split", "tag"],
    judge_score: ["judge_score", "score", "probability", "confidence", "llm_score"],
    id: ["id", "item_id", "case_id", "example_id", "question"]
  };

  function guessColumns(columns) {
    var lower = {}, out = {};
    columns.forEach(function (c) { lower[c.toLowerCase()] = c; });
    Object.keys(GUESS).forEach(function (k) {
      out[k] = null;
      for (var i = 0; i < GUESS[k].length; i++) if (lower[GUESS[k][i]] != null) { out[k] = lower[GUESS[k][i]]; break; }
    });
    return out;
  }

  var api = { asBool: asBool, kappa: kappa, kappaCI: kappaCI, calibrate: calibrate, parse: parse,
              parseCSV: parseCSV, guessColumns: guessColumns, band: band };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HoldlineJudge = api;
})(this);
