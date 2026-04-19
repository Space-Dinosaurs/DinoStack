export type Token = { kind: string; value: string };

export function parse(input: string): Token[] {
  const tokens: Token[] = [];
  for (const line of input.split("\n")) {
    if (!line.trim()) continue;
    tokens.push({ kind: "line", value: line });
  }
  return tokens;
}
