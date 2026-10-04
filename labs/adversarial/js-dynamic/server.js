const express = require("express");
const app = express();
const id = "/dynamic";
const base = "/api";

// app.get("/commented", x);
const s = "app.post(\"/in-a-string\", y)";
app.get(`/tpl/${id}`, h);
app.get(id, h);
app.get(base + "/concat", h);
