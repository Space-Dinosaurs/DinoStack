# docs/blog/

Static blog for the docs site (docs.dinostack.ai/blog/): `index.html` lists the posts, each post is one HTML file styled by `blog.css`, and diagrams live in `images/`. No framework and no build step.

## Authoring rules

- **One file per post,** named `YYYY-MM-DD-<slug>.html`, with the slug matching the title. Add each new post to the list in `index.html`, newest first.
- **Posts are feature-led.** Each post is about what a DinoStack feature does and why it matters. A priority claim ("we shipped it first") is optional supporting context, only when verified, with its sources, and never the headline or the angle.
- **Every factual claim must cite a source that states it.** Every post ends with a Sources list. If a claim cannot be sourced, delete it rather than rewording it.
- **At least two images per post,** saved under `images/`, each referenced by an `<img>` with meaningful alt text and wrapped in a link to the full-size file.
- **Diagrams are hand-drawn SVGs about 600 units wide, with labels of 17px or more,** so they stay readable on a phone. Each draws an explicit background or explicit fills so it reads in light and dark themes.
- **Root-absolute paths only:** `/blog/blog.css`, `/blog/images/...`, `/blog/<post>.html`, `/blog/`, so links resolve whether or not the URL has a trailing slash.
- **Plain hyphens only, never em dashes.**
