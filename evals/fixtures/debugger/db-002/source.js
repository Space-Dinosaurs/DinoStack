// API gateway request handler.
// Reads an auth context from req.session and looks up the user's
// active organization to enforce tenant isolation.

function handleRequest(req, res, next) {
  // session is populated by middleware earlier in the chain, but NOT
  // for unauthenticated routes (e.g. /health, /login). When this
  // handler is reached for an unauthenticated route, req.session is
  // undefined.
  const orgId = req.session.activeOrg.id;  // <-- throws when session is undefined
  const user = req.session.user;

  if (!orgId) {
    res.status(400).send("missing org");
    return;
  }
  req.tenantId = orgId;
  req.userId = user.id;
  next();
}

module.exports = { handleRequest };
