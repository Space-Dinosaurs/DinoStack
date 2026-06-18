# Third-Party Notices

This file lists the third-party dependencies used by DinoStack and the licenses they are distributed under. DinoStack itself is licensed under Apache-2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

The dependencies below support the Marp slide-build toolchain in `scripts/` (see `scripts/package.json`). The list is generated from the resolved dependency tree in `scripts/package-lock.json` using [`license-checker`](https://www.npmjs.com/package/license-checker); package names, versions, licenses, and links reflect the metadata each package declares. Licenses marked `UNKNOWN` would indicate a package that does not declare one - none were found.

All 153 third-party packages are distributed under permissive, Apache-2.0-compatible licenses (0BSD, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, MIT, MIT-0, Python-2.0). No copyleft (GPL/LGPL/AGPL/MPL/etc.) or unknown licenses are present.

## License summary

| License (SPDX) | Packages |
| --- | ---: |
| 0BSD | 1 |
| Apache-2.0 | 17 |
| BSD-2-Clause | 6 |
| BSD-3-Clause | 4 |
| ISC | 11 |
| MIT | 109 |
| MIT-0 | 4 |
| Python-2.0 | 1 |
| **Total** | **153** |

## npm dependencies

Source: `scripts/package.json` -> `scripts/package-lock.json` (transitive tree included).

| Package | Version | License (SPDX) | Link |
| --- | --- | --- | --- |
| `@babel/code-frame` | 7.29.0 | MIT | [https://github.com/babel/babel](https://github.com/babel/babel) |
| `@babel/helper-validator-identifier` | 7.28.5 | MIT | [https://github.com/babel/babel](https://github.com/babel/babel) |
| `@csstools/postcss-is-pseudo-class` | 5.0.3 | MIT-0 | [https://github.com/csstools/postcss-plugins](https://github.com/csstools/postcss-plugins) |
| `@csstools/selector-resolve-nested` | 3.1.0 | MIT-0 | [https://github.com/csstools/postcss-plugins](https://github.com/csstools/postcss-plugins) |
| `@csstools/selector-specificity` | 5.0.0 | MIT-0 | [https://github.com/csstools/postcss-plugins](https://github.com/csstools/postcss-plugins) |
| `@marp-team/marp-cli` | 4.3.1 | MIT | [https://github.com/marp-team/marp-cli](https://github.com/marp-team/marp-cli) |
| `@marp-team/marp-core` | 4.3.0 | MIT | [https://github.com/marp-team/marp-core](https://github.com/marp-team/marp-core) |
| `@marp-team/marpit` | 3.2.1 | MIT | [https://github.com/marp-team/marpit](https://github.com/marp-team/marpit) |
| `@marp-team/marpit-svg-polyfill` | 2.1.0 | MIT | [https://github.com/marp-team/marpit-svg-polyfill](https://github.com/marp-team/marpit-svg-polyfill) |
| `@puppeteer/browsers` | 2.13.2 | Apache-2.0 | [https://github.com/puppeteer/puppeteer/tree/main/packages/browsers](https://github.com/puppeteer/puppeteer/tree/main/packages/browsers) |
| `@tootallnate/quickjs-emscripten` | 0.23.0 | MIT | [https://github.com/justjake/quickjs-emscripten](https://github.com/justjake/quickjs-emscripten) |
| `@types/node` | 25.9.0 | MIT | [https://github.com/DefinitelyTyped/DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped) |
| `@types/yauzl` | 2.10.3 | MIT | [https://github.com/DefinitelyTyped/DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped) |
| `@xmldom/xmldom` | 0.9.10 | MIT | [https://github.com/xmldom/xmldom](https://github.com/xmldom/xmldom) |
| `accepts` | 1.3.8 | MIT | [https://github.com/jshttp/accepts](https://github.com/jshttp/accepts) |
| `agent-base` | 7.1.4 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `ansi-regex` | 5.0.1 | MIT | [https://github.com/chalk/ansi-regex](https://github.com/chalk/ansi-regex) |
| `ansi-styles` | 4.3.0 | MIT | [https://github.com/chalk/ansi-styles](https://github.com/chalk/ansi-styles) |
| `argparse` | 2.0.1 | Python-2.0 | [https://github.com/nodeca/argparse](https://github.com/nodeca/argparse) |
| `ast-types` | 0.13.4 | MIT | [https://github.com/benjamn/ast-types](https://github.com/benjamn/ast-types) |
| `b4a` | 1.8.1 | Apache-2.0 | [https://github.com/holepunchto/b4a](https://github.com/holepunchto/b4a) |
| `bare-events` | 2.8.3 | Apache-2.0 | [https://github.com/holepunchto/bare-events](https://github.com/holepunchto/bare-events) |
| `bare-fs` | 4.7.1 | Apache-2.0 | [https://github.com/holepunchto/bare-fs](https://github.com/holepunchto/bare-fs) |
| `bare-os` | 3.9.1 | Apache-2.0 | [https://github.com/holepunchto/bare-os](https://github.com/holepunchto/bare-os) |
| `bare-path` | 3.0.0 | Apache-2.0 | [https://github.com/holepunchto/bare-path](https://github.com/holepunchto/bare-path) |
| `bare-stream` | 2.13.1 | Apache-2.0 | [https://github.com/holepunchto/bare-stream](https://github.com/holepunchto/bare-stream) |
| `bare-url` | 2.4.3 | Apache-2.0 | [https://github.com/holepunchto/bare-url](https://github.com/holepunchto/bare-url) |
| `basic-ftp` | 5.3.1 | MIT | [https://github.com/patrickjuchli/basic-ftp](https://github.com/patrickjuchli/basic-ftp) |
| `batch` | 0.6.1 | MIT | [https://github.com/visionmedia/batch](https://github.com/visionmedia/batch) |
| `buffer-crc32` | 0.2.13 | MIT | [https://github.com/brianloveswords/buffer-crc32](https://github.com/brianloveswords/buffer-crc32) |
| `callsites` | 3.1.0 | MIT | [https://github.com/sindresorhus/callsites](https://github.com/sindresorhus/callsites) |
| `chokidar` | 4.0.3 | MIT | [https://github.com/paulmillr/chokidar](https://github.com/paulmillr/chokidar) |
| `chromium-bidi` | 14.0.0 | Apache-2.0 | [https://github.com/GoogleChromeLabs/chromium-bidi](https://github.com/GoogleChromeLabs/chromium-bidi) |
| `cliui` | 8.0.1 | ISC | [https://github.com/yargs/cliui](https://github.com/yargs/cliui) |
| `color-convert` | 2.0.1 | MIT | [https://github.com/Qix-/color-convert](https://github.com/Qix-/color-convert) |
| `color-name` | 1.1.4 | MIT | [https://github.com/colorjs/color-name](https://github.com/colorjs/color-name) |
| `commander` | 13.1.0 | MIT | [https://github.com/tj/commander.js](https://github.com/tj/commander.js) |
| `commander` | 2.20.3 | MIT | [https://github.com/tj/commander.js](https://github.com/tj/commander.js) |
| `commander` | 8.3.0 | MIT | [https://github.com/tj/commander.js](https://github.com/tj/commander.js) |
| `cosmiconfig` | 9.0.1 | MIT | [https://github.com/cosmiconfig/cosmiconfig](https://github.com/cosmiconfig/cosmiconfig) |
| `cssesc` | 3.0.0 | MIT | [https://github.com/mathiasbynens/cssesc](https://github.com/mathiasbynens/cssesc) |
| `cssfilter` | 0.0.10 | MIT | [https://github.com/leizongmin/js-css-filter](https://github.com/leizongmin/js-css-filter) |
| `data-uri-to-buffer` | 6.0.2 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `debug` | 2.6.9 | MIT | [https://github.com/visionmedia/debug](https://github.com/visionmedia/debug) |
| `debug` | 4.4.3 | MIT | [https://github.com/debug-js/debug](https://github.com/debug-js/debug) |
| `degenerator` | 5.0.1 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `depd` | 1.1.2 | MIT | [https://github.com/dougwilson/nodejs-depd](https://github.com/dougwilson/nodejs-depd) |
| `devtools-protocol` | 0.0.1608973 | BSD-3-Clause | [https://github.com/ChromeDevTools/devtools-protocol](https://github.com/ChromeDevTools/devtools-protocol) |
| `emoji-regex` | 8.0.0 | MIT | [https://github.com/mathiasbynens/emoji-regex](https://github.com/mathiasbynens/emoji-regex) |
| `end-of-stream` | 1.4.5 | MIT | [https://github.com/mafintosh/end-of-stream](https://github.com/mafintosh/end-of-stream) |
| `entities` | 4.5.0 | BSD-2-Clause | [https://github.com/fb55/entities](https://github.com/fb55/entities) |
| `env-paths` | 2.2.1 | MIT | [https://github.com/sindresorhus/env-paths](https://github.com/sindresorhus/env-paths) |
| `error-ex` | 1.3.4 | MIT | [https://github.com/qix-/node-error-ex](https://github.com/qix-/node-error-ex) |
| `escalade` | 3.2.0 | MIT | [https://github.com/lukeed/escalade](https://github.com/lukeed/escalade) |
| `escape-html` | 1.0.3 | MIT | [https://github.com/component/escape-html](https://github.com/component/escape-html) |
| `escodegen` | 2.1.0 | BSD-2-Clause | [https://github.com/estools/escodegen](https://github.com/estools/escodegen) |
| `esm` | 3.2.25 | MIT | [https://github.com/standard-things/esm](https://github.com/standard-things/esm) |
| `esprima` | 4.0.1 | BSD-2-Clause | [https://github.com/jquery/esprima](https://github.com/jquery/esprima) |
| `estraverse` | 5.3.0 | BSD-2-Clause | [https://github.com/estools/estraverse](https://github.com/estools/estraverse) |
| `esutils` | 2.0.3 | BSD-2-Clause | [https://github.com/estools/esutils](https://github.com/estools/esutils) |
| `events-universal` | 1.0.1 | Apache-2.0 | [https://github.com/holepunchto/events-universal](https://github.com/holepunchto/events-universal) |
| `extract-zip` | 2.0.1 | BSD-2-Clause | [https://github.com/maxogden/extract-zip](https://github.com/maxogden/extract-zip) |
| `fast-fifo` | 1.3.2 | MIT | [https://github.com/mafintosh/fast-fifo](https://github.com/mafintosh/fast-fifo) |
| `fd-slicer` | 1.1.0 | MIT | [https://github.com/andrewrk/node-fd-slicer](https://github.com/andrewrk/node-fd-slicer) |
| `get-caller-file` | 2.0.5 | ISC | [https://github.com/stefanpenner/get-caller-file](https://github.com/stefanpenner/get-caller-file) |
| `get-stream` | 5.2.0 | MIT | [https://github.com/sindresorhus/get-stream](https://github.com/sindresorhus/get-stream) |
| `get-uri` | 6.0.5 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `highlight.js` | 11.11.1 | BSD-3-Clause | [https://github.com/highlightjs/highlight.js](https://github.com/highlightjs/highlight.js) |
| `http-errors` | 1.8.1 | MIT | [https://github.com/jshttp/http-errors](https://github.com/jshttp/http-errors) |
| `http-proxy-agent` | 7.0.2 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `https-proxy-agent` | 7.0.6 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `import-fresh` | 3.3.1 | MIT | [https://github.com/sindresorhus/import-fresh](https://github.com/sindresorhus/import-fresh) |
| `inherits` | 2.0.4 | ISC | [https://github.com/isaacs/inherits](https://github.com/isaacs/inherits) |
| `ip-address` | 10.2.0 | MIT | [https://github.com/beaugunderson/ip-address](https://github.com/beaugunderson/ip-address) |
| `is-arrayish` | 0.2.1 | MIT | [https://github.com/qix-/node-is-arrayish](https://github.com/qix-/node-is-arrayish) |
| `is-fullwidth-code-point` | 3.0.0 | MIT | [https://github.com/sindresorhus/is-fullwidth-code-point](https://github.com/sindresorhus/is-fullwidth-code-point) |
| `js-tokens` | 4.0.0 | MIT | [https://github.com/lydell/js-tokens](https://github.com/lydell/js-tokens) |
| `js-yaml` | 4.1.1 | MIT | [https://github.com/nodeca/js-yaml](https://github.com/nodeca/js-yaml) |
| `json-parse-even-better-errors` | 2.3.1 | MIT | [https://github.com/npm/json-parse-even-better-errors](https://github.com/npm/json-parse-even-better-errors) |
| `katex` | 0.16.47 | MIT | [https://github.com/KaTeX/KaTeX](https://github.com/KaTeX/KaTeX) |
| `lines-and-columns` | 1.2.4 | MIT | [https://github.com/eventualbuddha/lines-and-columns](https://github.com/eventualbuddha/lines-and-columns) |
| `linkify-it` | 5.0.0 | MIT | [https://github.com/markdown-it/linkify-it](https://github.com/markdown-it/linkify-it) |
| `lodash.kebabcase` | 4.1.1 | MIT | [https://github.com/lodash/lodash](https://github.com/lodash/lodash) |
| `lru-cache` | 7.18.3 | ISC | [https://github.com/isaacs/node-lru-cache](https://github.com/isaacs/node-lru-cache) |
| `markdown-it` | 14.1.1 | MIT | [https://github.com/markdown-it/markdown-it](https://github.com/markdown-it/markdown-it) |
| `markdown-it-front-matter` | 0.2.4 | MIT | [https://github.com/ParkSB/markdown-it-front-matter](https://github.com/ParkSB/markdown-it-front-matter) |
| `mathjax-full` | 3.2.2 | Apache-2.0 | [https://github.com/mathjax/Mathjax-src](https://github.com/mathjax/Mathjax-src) |
| `mdurl` | 2.0.0 | MIT | [https://github.com/markdown-it/mdurl](https://github.com/markdown-it/mdurl) |
| `mhchemparser` | 4.2.1 | Apache-2.0 | [https://github.com/mhchem/mhchemParser](https://github.com/mhchem/mhchemParser) |
| `mime-db` | 1.52.0 | MIT | [https://github.com/jshttp/mime-db](https://github.com/jshttp/mime-db) |
| `mime-types` | 2.1.35 | MIT | [https://github.com/jshttp/mime-types](https://github.com/jshttp/mime-types) |
| `mitt` | 3.0.1 | MIT | [https://github.com/developit/mitt](https://github.com/developit/mitt) |
| `mj-context-menu` | 0.6.1 | Apache-2.0 | [https://github.com/zorkow/context-menu](https://github.com/zorkow/context-menu) |
| `ms` | 2.0.0 | MIT | [https://github.com/zeit/ms](https://github.com/zeit/ms) |
| `ms` | 2.1.3 | MIT | [https://github.com/vercel/ms](https://github.com/vercel/ms) |
| `nanoid` | 3.3.12 | MIT | [https://github.com/ai/nanoid](https://github.com/ai/nanoid) |
| `negotiator` | 0.6.3 | MIT | [https://github.com/jshttp/negotiator](https://github.com/jshttp/negotiator) |
| `netmask` | 2.1.1 | MIT | [https://github.com/rs/node-netmask](https://github.com/rs/node-netmask) |
| `once` | 1.4.0 | ISC | [https://github.com/isaacs/once](https://github.com/isaacs/once) |
| `pac-proxy-agent` | 7.2.0 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `pac-resolver` | 7.0.1 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `parent-module` | 1.0.1 | MIT | [https://github.com/sindresorhus/parent-module](https://github.com/sindresorhus/parent-module) |
| `parse-json` | 5.2.0 | MIT | [https://github.com/sindresorhus/parse-json](https://github.com/sindresorhus/parse-json) |
| `parseurl` | 1.3.3 | MIT | [https://github.com/pillarjs/parseurl](https://github.com/pillarjs/parseurl) |
| `pend` | 1.2.0 | MIT | [https://github.com/andrewrk/node-pend](https://github.com/andrewrk/node-pend) |
| `picocolors` | 1.1.1 | ISC | [https://github.com/alexeyraspopov/picocolors](https://github.com/alexeyraspopov/picocolors) |
| `postcss` | 8.5.14 | MIT | [https://github.com/postcss/postcss](https://github.com/postcss/postcss) |
| `postcss-nesting` | 13.0.2 | MIT-0 | [https://github.com/csstools/postcss-plugins](https://github.com/csstools/postcss-plugins) |
| `postcss-selector-parser` | 7.1.1 | MIT | [https://github.com/postcss/postcss-selector-parser](https://github.com/postcss/postcss-selector-parser) |
| `progress` | 2.0.3 | MIT | [https://github.com/visionmedia/node-progress](https://github.com/visionmedia/node-progress) |
| `proxy-agent` | 6.5.0 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `proxy-from-env` | 1.1.0 | MIT | [https://github.com/Rob--W/proxy-from-env](https://github.com/Rob--W/proxy-from-env) |
| `pump` | 3.0.4 | MIT | [https://github.com/mafintosh/pump](https://github.com/mafintosh/pump) |
| `punycode.js` | 2.3.1 | MIT | [https://github.com/mathiasbynens/punycode.js](https://github.com/mathiasbynens/punycode.js) |
| `puppeteer-core` | 24.43.1 | Apache-2.0 | [https://github.com/puppeteer/puppeteer/tree/main/packages/puppeteer-core](https://github.com/puppeteer/puppeteer/tree/main/packages/puppeteer-core) |
| `readdirp` | 4.1.2 | MIT | [https://github.com/paulmillr/readdirp](https://github.com/paulmillr/readdirp) |
| `require-directory` | 2.1.1 | MIT | [https://github.com/troygoode/node-require-directory](https://github.com/troygoode/node-require-directory) |
| `resolve-from` | 4.0.0 | MIT | [https://github.com/sindresorhus/resolve-from](https://github.com/sindresorhus/resolve-from) |
| `semver` | 7.8.0 | ISC | [https://github.com/npm/node-semver](https://github.com/npm/node-semver) |
| `serve-index` | 1.9.2 | MIT | [https://github.com/expressjs/serve-index](https://github.com/expressjs/serve-index) |
| `setprototypeof` | 1.2.0 | ISC | [https://github.com/wesleytodd/setprototypeof](https://github.com/wesleytodd/setprototypeof) |
| `smart-buffer` | 4.2.0 | MIT | [https://github.com/JoshGlazebrook/smart-buffer](https://github.com/JoshGlazebrook/smart-buffer) |
| `socks` | 2.8.9 | MIT | [https://github.com/JoshGlazebrook/socks](https://github.com/JoshGlazebrook/socks) |
| `socks-proxy-agent` | 8.0.5 | MIT | [https://github.com/TooTallNate/proxy-agents](https://github.com/TooTallNate/proxy-agents) |
| `source-map` | 0.6.1 | BSD-3-Clause | [https://github.com/mozilla/source-map](https://github.com/mozilla/source-map) |
| `source-map-js` | 1.2.1 | BSD-3-Clause | [https://github.com/7rulnik/source-map-js](https://github.com/7rulnik/source-map-js) |
| `speech-rule-engine` | 4.1.4 | Apache-2.0 | [https://github.com/zorkow/speech-rule-engine](https://github.com/zorkow/speech-rule-engine) |
| `statuses` | 1.5.0 | MIT | [https://github.com/jshttp/statuses](https://github.com/jshttp/statuses) |
| `streamx` | 2.25.0 | MIT | [https://github.com/mafintosh/streamx](https://github.com/mafintosh/streamx) |
| `string-width` | 4.2.3 | MIT | [https://github.com/sindresorhus/string-width](https://github.com/sindresorhus/string-width) |
| `strip-ansi` | 6.0.1 | MIT | [https://github.com/chalk/strip-ansi](https://github.com/chalk/strip-ansi) |
| `tar-fs` | 3.1.2 | MIT | [https://github.com/mafintosh/tar-fs](https://github.com/mafintosh/tar-fs) |
| `tar-stream` | 3.2.0 | MIT | [https://github.com/mafintosh/tar-stream](https://github.com/mafintosh/tar-stream) |
| `teex` | 1.0.1 | MIT | [https://github.com/mafintosh/teex](https://github.com/mafintosh/teex) |
| `text-decoder` | 1.2.7 | Apache-2.0 | [https://github.com/holepunchto/text-decoder](https://github.com/holepunchto/text-decoder) |
| `tmp` | 0.2.7 | MIT | [https://github.com/raszi/node-tmp](https://github.com/raszi/node-tmp) |
| `toidentifier` | 1.0.1 | MIT | [https://github.com/component/toidentifier](https://github.com/component/toidentifier) |
| `tslib` | 2.8.1 | 0BSD | [https://github.com/Microsoft/tslib](https://github.com/Microsoft/tslib) |
| `typed-query-selector` | 2.12.2 | MIT | [https://github.com/g-plane/typed-query-selector](https://github.com/g-plane/typed-query-selector) |
| `uc.micro` | 2.1.0 | MIT | [https://github.com/markdown-it/uc.micro](https://github.com/markdown-it/uc.micro) |
| `undici-types` | 7.24.6 | MIT | [https://github.com/nodejs/undici](https://github.com/nodejs/undici) |
| `util-deprecate` | 1.0.2 | MIT | [https://github.com/TooTallNate/util-deprecate](https://github.com/TooTallNate/util-deprecate) |
| `webdriver-bidi-protocol` | 0.4.1 | Apache-2.0 | [https://github.com/GoogleChromeLabs/webdriver-bidi-protocol](https://github.com/GoogleChromeLabs/webdriver-bidi-protocol) |
| `wicked-good-xpath` | 1.3.0 | MIT | [https://github.com/google/wicked-good-xpath](https://github.com/google/wicked-good-xpath) |
| `wrap-ansi` | 7.0.0 | MIT | [https://github.com/chalk/wrap-ansi](https://github.com/chalk/wrap-ansi) |
| `wrappy` | 1.0.2 | ISC | [https://github.com/npm/wrappy](https://github.com/npm/wrappy) |
| `ws` | 8.20.1 | MIT | [https://github.com/websockets/ws](https://github.com/websockets/ws) |
| `xss` | 1.0.15 | MIT | [https://github.com/leizongmin/js-xss](https://github.com/leizongmin/js-xss) |
| `y18n` | 5.0.8 | ISC | [https://github.com/yargs/y18n](https://github.com/yargs/y18n) |
| `yargs` | 17.7.2 | MIT | [https://github.com/yargs/yargs](https://github.com/yargs/yargs) |
| `yargs-parser` | 21.1.1 | ISC | [https://github.com/yargs/yargs-parser](https://github.com/yargs/yargs-parser) |
| `yauzl` | 2.10.0 | MIT | [https://github.com/thejoshwolfe/yauzl](https://github.com/thejoshwolfe/yauzl) |
| `zod` | 3.25.76 | MIT | [https://github.com/colinhacks/zod](https://github.com/colinhacks/zod) |

---

Generated for DS-23. Regenerate after dependency changes with `npx license-checker --json` from `scripts/`.
