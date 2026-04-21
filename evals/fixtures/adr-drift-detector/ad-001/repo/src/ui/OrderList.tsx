import React from "react";
import { Order } from "../domain/order";

export function OrderList({ orders }: { orders: Order[] }) {
  return (
    <ul>
      {orders.map((o) => (
        <li key={o.id}>{o.id}: {o.total}</li>
      ))}
    </ul>
  );
}
