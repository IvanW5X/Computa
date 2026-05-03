// Entry point: loads .env, reads config files, initializes the Discord client,
// starts the bot, and boots the dashboard HTTP server alongside it.

require("dotenv").config();

const { app: dashboardApp } = require("./dashboard/server");

const DASHBOARD_PORT = Number(process.env.DASHBOARD_PORT || 3000);

dashboardApp.listen(DASHBOARD_PORT, () => {
  console.log(`Computa dashboard on http://localhost:${DASHBOARD_PORT}`);
});

// Discord wiring lives in src/discord-handler.js — left as a stub for now;
// dashboard receives turns via HTTP POST /log from OpenClaw skills.
