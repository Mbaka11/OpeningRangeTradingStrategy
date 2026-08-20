# Documentation assets

This folder stores images used by the project README and other documentation. Add only real documentation assets, with descriptive file names.

## X post examples

See [`tweet-flow-examples.md`](tweet-flow-examples.md) for the two supported posting flows:

- Trade day: opening-range/signal post plus final trade recap.
- No-trade day: one consolidated session recap.

Regenerate the example text and dark-theme charts with:

```bash
python scripts/generate_example_assets.py
```

From the top-level `README.md`, reference an image with a relative Markdown path:

```markdown
![Opening range example](docs/assets/opening-range-example.png)
```

From a Markdown file inside `docs/`, use a path relative to that file, for example:

```markdown
![Opening range example](assets/opening-range-example.png)
```
