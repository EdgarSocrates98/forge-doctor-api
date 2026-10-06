'use strict'

var express = require('express')
var app = express()
var handler = function (req, res) { res.end('ok') }

// computed verb — the adapter cannot evidence a method for dynamic dispatch
app[process.env.HTTP_VERB || 'get']('/dyn', handler)

// concatenated path — the literal prefix is partial evidence only
app.get('/users/' + process.env.SUFFIX, handler)

app.get('/health', handler)

module.exports = app
