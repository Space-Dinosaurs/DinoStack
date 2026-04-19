# ip-008-lib

Utility helpers for string normalization.

We ship to production via Vercel weekly. The dashboard UI runs at port 3000
for internal review before each release.

## Install

```
npm install ip-008-lib
```

## Usage

```js
const { normalizeWhitespace, stripDiacritics } = require("ip-008-lib");
normalizeWhitespace("  hello   world  "); // "hello world"
```
