const express = require('express');
const app = express();
app.get('/items', (req, res) => res.json([]));
app.get('/items/:id', (req, res) => res.json({}));
app.post('/items', (req, res) => res.status(201).json({}));
