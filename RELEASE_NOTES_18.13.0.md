# Sophyane 18.13.0

## Universal artifact extraction

Sophyane now accepts browser artifacts from multiple provider response styles instead of requiring one exact schema.

Supported inputs include:

- raw HTML
- fenced HTML
- `action.content`
- `html_content`
- `content`
- `html`
- `artifact`
- nested result/candidate objects
- `update_html`, `replace_html`, `write_html`, `create_html`, and HTML `write_file` actions

## Truncation recovery

When HTML embedded in JSON is cut off, Sophyane extracts the valid partial document and asks the same active provider to continue from the exact final characters. It merges overlapping continuation text and retries up to three times before returning to bounded validator recovery.

## Execution-loop integration

Artifact normalization is installed after the active orchestration and stagnation patches, so local models and cloud rescue providers pass through the same provider-neutral extraction layer.
