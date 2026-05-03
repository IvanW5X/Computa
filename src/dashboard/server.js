// Express dashboard. Reads logs/calls.jsonl on every request — small file, fine
// for the demo. Exposes /api/stats, /api/recent, /api/burst, and serves the UI.

const path = require("node:path");
const express = require("express");
const { readAllRecords, LOG_PATH } = require("../logger");
const { routePrompt } = require("../llm");

const PORT = Number(process.env.DASHBOARD_PORT || 3000);

// Pricing reference (USD per million tokens). Tweak here.
const PRICING = {
  big_model_input_per_million: 0.20,
  big_model_output_per_million: 0.60,
  local_per_million: 0.0,
};

// Pre-seeded burst prompts for the live demo. Mix of simple + complex so the
// dashboard shows both routes lighting up.
const BURST_PROMPTS = [
  "what time is it in Tokyo right now?",
  "translate 'good morning' to french",
  "give me a one-line definition of REST",
  "what is 17 * 23?",
  "summarize the first law of thermodynamics in one sentence",
  "say hi",
  "convert 30 celsius to fahrenheit",
  "list three primary colors",
  "write a haiku about coffee",
  "what's the capital of Australia?",
  "design a multi-region failover architecture for a Postgres cluster with sub-second RPO and explain the tradeoffs",
  "prove that the sum of two odd numbers is even using formal mathematical notation",
  "draft a GDPR-compliant data processing addendum between a SaaS vendor and an EU customer covering subprocessor obligations",
  "derive the closed-form solution to the Black-Scholes PDE and explain the boundary conditions",
  "design a token-bucket rate limiter that handles bursty traffic with fair queuing across tenants and prove its correctness",
  "review this auth flow for OWASP top-10 vulnerabilities: user submits creds, server hashes with sha1, stores session id in cookie without httpOnly",
  "write a 2000-word strategy memo on entering the Southeast Asian fintech market with regulatory analysis for Singapore, Indonesia, and Vietnam",
  "diagnose: kernel panic on Linux 6.1, kthread_create_on_node, BUG_ON in mm/page_alloc.c during heavy NUMA workload — propose root cause",
  "translate this contract clause to plain English and flag legally risky language: 'Indemnitor shall hold harmless and defend Indemnitee against any and all third-party claims arising out of or in connection with...'",
  "write a complete proof of the Cook-Levin theorem suitable for a graduate complexity theory course",
];

function cost(tokens, perMillion) {
  return (tokens * perMillion) / 1_000_000;
}

function aggregate(records) {
  // Token sums roll up every record, but baseline + classification + prompt
  // counts are per-prompt — dedupe on prompt_id to avoid multi-counting when
  // a single prompt produces several log rows (classify + answer / optimize
  // + escalate).
  let localIn = 0;
  let localOut = 0;
  let remoteIn = 0;
  let remoteOut = 0;

  const byPrompt = new Map();
  for (const r of records) {
    localIn += r.local_tokens_in | 0;
    localOut += r.local_tokens_out | 0;
    remoteIn += r.remote_tokens_in | 0;
    remoteOut += r.remote_tokens_out | 0;

    const id = r.prompt_id || `_${Math.random()}`;
    const cur = byPrompt.get(id) || {
      classification: "unknown",
      baseline: 0,
    };
    if (r.classification === "complex" || r.classification === "simple") {
      // Prefer "complex" if any record says so (escalation path).
      if (cur.classification !== "complex") cur.classification = r.classification;
    }
    cur.baseline = Math.max(cur.baseline, r.baseline_tokens_estimate | 0);
    byPrompt.set(id, cur);
  }

  let totalPrompts = byPrompt.size;
  let simple = 0;
  let complex = 0;
  let baselineTotal = 0;
  for (const v of byPrompt.values()) {
    if (v.classification === "complex") complex++;
    else if (v.classification === "simple") simple++;
    baselineTotal += v.baseline;
  }

  // Hybrid cost = only remote tokens billed (local is free).
  const hybridCost =
    cost(remoteIn, PRICING.big_model_input_per_million) +
    cost(remoteOut, PRICING.big_model_output_per_million);

  // Baseline cost = full prompt + 250 estimated completion if everything had
  // gone to the big model. Split the baseline ~ as input vs output for cost:
  // baseline_tokens_estimate already bakes in 250 output tokens, so:
  //   baseline_input = baseline_total - 250 * num_records
  //   baseline_output = 250 * num_records
  const assumedOut = 250 * totalPrompts;
  const baselineIn = Math.max(0, baselineTotal - assumedOut);
  const baselineOut = assumedOut;
  const baselineCost =
    cost(baselineIn, PRICING.big_model_input_per_million) +
    cost(baselineOut, PRICING.big_model_output_per_million);

  const dollarsSaved = Math.max(0, baselineCost - hybridCost);
  const tokensSaved = Math.max(
    0,
    baselineTotal - (remoteIn + remoteOut)
  );
  const percentSaved =
    baselineCost > 0 ? (dollarsSaved / baselineCost) * 100 : 0;

  return {
    pricing: PRICING,
    total_prompts: totalPrompts,
    simple_count: simple,
    complex_count: complex,
    local_tokens_in: localIn,
    local_tokens_out: localOut,
    remote_tokens_in: remoteIn,
    remote_tokens_out: remoteOut,
    baseline_total_tokens: baselineTotal,
    hybrid_total_tokens: remoteIn + remoteOut,
    tokens_saved: tokensSaved,
    hybrid_cost_usd: hybridCost,
    baseline_cost_usd: baselineCost,
    dollars_saved: dollarsSaved,
    percent_saved: percentSaved,
  };
}

const app = express();
app.use(express.json({ limit: "1mb" }));
app.use(express.static(path.join(__dirname, "public")));

app.get("/api/stats", (_req, res) => {
  const records = readAllRecords();
  res.json(aggregate(records));
});

app.get("/api/recent", (req, res) => {
  const n = Math.max(1, Math.min(500, Number(req.query.n) || 10));
  const records = readAllRecords();
  res.json(records.slice(-n).reverse());
});

app.get("/api/burst", async (_req, res) => {
  // Fire the demo prompts through the routing pipeline. We don't await every
  // call serially in the response — kick them off, return immediately so the
  // dashboard sees them stream in via the 1s poll.
  res.json({ ok: true, count: BURST_PROMPTS.length });
  for (const p of BURST_PROMPTS) {
    routePrompt(p).catch((e) =>
      console.error("[burst] route failed:", e.message)
    );
  }
});

app.get("/api/log-path", (_req, res) => res.json({ path: LOG_PATH }));

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Computa dashboard on http://localhost:${PORT}`);
  });
}

module.exports = { app, aggregate, PRICING, BURST_PROMPTS };
