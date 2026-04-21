export interface Order {
  id: string;
  total: number;
}

export function totalCents(order: Order): number {
  return Math.round(order.total * 100);
}
