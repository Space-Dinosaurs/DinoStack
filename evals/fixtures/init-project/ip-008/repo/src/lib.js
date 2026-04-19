"use strict";

function normalizeWhitespace(input) {
  if (typeof input !== "string") {
    throw new TypeError("normalizeWhitespace expects a string");
  }
  return input.replace(/\s+/g, " ").trim();
}

function stripDiacritics(input) {
  return input.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

module.exports = { normalizeWhitespace, stripDiacritics };
