// Seeds the dashboard DB with a demo conversation so the charts have
// something to show before the bot is wired up. Run: node scripts/seed_demo.js
//
// Token model: local_prompt = full raw context the drafter sees. On escalation
// the drafter compresses to a tiny handoff payload, so cloud_prompt is much
// smaller than local_prompt. Counterfactual baseline = local_prompt (cloud-only
// pipeline has no drafter, so it pays the full context every turn).

const { recordTurn, db } = require("../src/memory");

const SESSION = "demo-session";

// Wipe prior demo turns so re-runs don't compound numbers.
db.prepare("DELETE FROM turns WHERE session_id = ?").run(SESSION);

const turns = [
  {
    user: "what does this repo do?",
    bot: "Hackathon scaffolding for a Discord bot with a small/big LLM split.",
    local_in: 480, local_out: 90,
    escalated: false,
  },
  {
    user: "summarize what we discussed so far",
    bot: "We covered the repo intent and the drafter+validator architecture.",
    local_in: 720, local_out: 110,
    escalated: false,
  },
  {
    user: "design a rate limiter that handles bursty traffic with token buckets",
    bot: "Use a leaky-token-bucket with refill rate r and capacity c... [validator pass]",
    local_in: 1100, local_out: 180,
    cloud_in: 140, cloud_out: 180,
    escalated: true,
  },
  {
    user: "give me three jokes about databases",
    bot: "1) ... 2) ... 3) ...",
    local_in: 1450, local_out: 95,
    escalated: false,
  },
  {
    user: "now translate the rate limiter pseudocode to Go and prove correctness",
    bot: "package ratelimit ... // proof sketch via invariant on bucket level",
    local_in: 1820, local_out: 320,
    cloud_in: 220, cloud_out: 320,
    escalated: true,
  },
  {
    user: "thanks",
    bot: "Anytime.",
    local_in: 2200, local_out: 14,
    escalated: false,
  },
];

for (const t of turns) {
  recordTurn({
    session_id: SESSION,
    user_msg: t.user,
    bot_reply: t.bot,
    user_msg_tokens: Math.ceil(t.user.length / 4),
    bot_reply_tokens: t.local_out,
    local_prompt_tokens: t.local_in,
    local_completion_tokens: t.local_out,
    cloud_prompt_tokens: t.cloud_in || 0,
    cloud_completion_tokens: t.cloud_out || 0,
    escalated: t.escalated,
  });
}

console.log(`Seeded ${turns.length} demo turns into session "${SESSION}".`);
