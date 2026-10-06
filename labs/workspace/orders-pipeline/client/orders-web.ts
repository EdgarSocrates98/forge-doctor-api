// web client for the Orders service — lives in a separate repo tree.
export async function fetchOrder(id: string): Promise<unknown> {
  const res = await fetch(`/orders/${id}`);
  return res.json();
}

export async function listOrders(): Promise<unknown> {
  const res = await fetch("/orders");
  return res.json();
}
