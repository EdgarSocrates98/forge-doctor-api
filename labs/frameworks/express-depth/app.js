// Express depth fixture: passport auth, registry DI, err-first
// middleware. No validator import — validation must be UNKNOWN.
const express = require("express");
const passport = require("passport");
const app = express();

function errHandler(err, req, res, next) {
  res.status(500).end();
}

app.use(passport.initialize());
app.get("/pets", passport.authenticate("jwt"), (req, res) =>
  res.send(req.app.get("db")));
app.use((err, req, res, next) => res.status(400).end());
app.use(errHandler);
app.set("db", pool);
app.locals.cache = new Map();
