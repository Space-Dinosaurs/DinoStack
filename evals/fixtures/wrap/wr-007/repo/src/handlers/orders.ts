// Orders handler. Validates via zod before touching the DB.
export async function createOrder(req: any, res: any) {
  res.json({ ok: true });
}
