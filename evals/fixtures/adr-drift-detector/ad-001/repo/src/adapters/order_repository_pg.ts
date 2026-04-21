import { Order } from "../domain/order";
import { OrderRepository } from "../ports/order_repository";

export class PgOrderRepository implements OrderRepository {
  async findById(id: string): Promise<Order | null> {
    // Adapter implementation elided.
    return null;
  }
  async save(order: Order): Promise<void> {
    // Adapter implementation elided.
  }
}
