import express from "express";
import { log } from "./logger";

const app = express();

app.get("/", (_req, res) => {
  log("root-hit");
  res.json({ hello: "world" });
});

app.get("/status", (_req, res) => {
  log("status-hit");
  res.json({ status: "up" });
});

export default app;
