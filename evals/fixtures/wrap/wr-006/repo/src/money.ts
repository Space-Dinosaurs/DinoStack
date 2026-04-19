// Money type: integer minor-units only.
export type Money = { amount: number; currency: string };

export function add(a: Money, b: Money): Money {
  if (a.currency !== b.currency) throw new Error("currency mismatch");
  return { amount: a.amount + b.amount, currency: a.currency };
}
