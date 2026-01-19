# Changelog

All notable changes to this project will be documented in this file.

## 2026-01-19

- Added `--force` option to `p3 fetch` to re-download existing episodes and update DB records by `url`.
- Added `--dry-run` option to `p3 fetch` to report actions without performing downloads or DB writes.
- Added per-feed `force` and `dry_run` configuration options in `config/feeds.yaml`.
- Added `P3Database.update_episode_file_path_by_url(...)` to update existing episode records on re-download.
- Broadened RSS audio detection (enclosures, links, media_content) and fetch parsing via `requests` for improved feed compatibility.
