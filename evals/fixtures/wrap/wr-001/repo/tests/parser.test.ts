import { parse } from "../src/parser";

test("parses lines", () => {
  expect(parse("a\nb").length).toBe(2);
});

test("skips blanks", () => {
  expect(parse("a\n\nb").length).toBe(2);
});
