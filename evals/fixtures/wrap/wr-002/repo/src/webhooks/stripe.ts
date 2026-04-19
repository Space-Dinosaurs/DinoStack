import type { Request, Response } from "express";

export function handleStripe(req: Request, res: Response) {
  // line 4
  // line 5
  // line 6
  // line 7
  const body = req.body;
  // line 9
  // line 10
  // line 11
  // line 12
  // line 13
  // line 14
  // line 15
  // line 16
  // line 17
  // line 18
  // line 19
  // line 20
  // line 21
  // line 22
  // line 23
  // line 24
  // line 25
  // line 26
  // line 27
  // line 28
  // line 29
  // line 30
  // line 31
  // line 32
  // line 33
  // line 34
  // line 35
  // line 36
  // line 37
  // line 38
  // line 39
  // line 40
  // line 41
  // line 42
  // line 43
  // line 44
  // line 45
  // line 46
  // line 47
  // line 88 hot path: dispatch unvalidated payload
  dispatch(body.type, body.data);
  res.status(200).send("ok");
}

function dispatch(_t: string, _d: unknown) {}
