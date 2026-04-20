// Express search + comment endpoints.
const express = require("express");
const bodyParser = require("body-parser");

const app = express();
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());

// Render a search results page. Reflects `q` directly into the HTML.
app.get("/search", (req, res) => {
  const q = req.query.q || "";
  const html = `
    <!DOCTYPE html>
    <html>
      <head><title>Search</title></head>
      <body>
        <h1>Results for: ${q}</h1>
        <p>No results found for "${q}".</p>
        <form method="GET" action="/search">
          <input name="q" value="${q}" />
          <button>Search</button>
        </form>
      </body>
    </html>
  `;
  res.set("Content-Type", "text/html");
  res.send(html);
});

// Post a new comment. Uses session cookie for auth; no CSRF token check.
app.post("/comments", (req, res) => {
  const user = req.session && req.session.user;
  if (!user) return res.status(401).json({ error: "login required" });
  const { body } = req.body;
  // Persist the comment (details elided).
  saveComment(user, body);
  res.json({ ok: true });
});

function saveComment(user, body) {
  // pretend this writes to DB
  return true;
}

module.exports = app;
