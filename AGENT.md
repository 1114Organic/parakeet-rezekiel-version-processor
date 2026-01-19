# P³ Development Guide

## Prerequisites

- **macOS with Apple Silicon** (M1/M2/M3/M4)
- **ffmpeg**: `brew install ffmpeg`
- **Ollama**: Download from https://ollama.com and install a model (e.g., `ollama pull llama3.2`)

## Setup Commands

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install P³ with all dependencies
pip install -e .

# Initialize P³
p3 init
```

## Configuration

Edit `config/feeds.yaml`:

```yaml
feeds:
  - name: "Your Podcast"
    url: "https://example.com/feed.xml"
    category: "tech"

settings:
  max_episodes_per_feed: 5
  
  # Transcription (Apple Silicon optimized)
  parakeet_enabled: true
  parakeet_model: "mlx-community/parakeet-tdt-0.6b-v2"
  
  # LLM Processing (Local)
  llm_provider: "ollama"
  llm_model: "llama3.2:latest"
```

## Daily Workflow

```bash
# Complete pipeline
p3 fetch        # RSS → Audio download with ffmpeg normalization
p3 transcribe   # Audio → Text with Parakeet MLX (30x faster than Whisper)
p3 digest       # Text → Structured analysis with Ollama
p3 export       # Generate markdown/JSON outputs

# Check status
p3 status
```

## Performance Results

- **Audio Download**: 1 episode ~30 seconds (with normalization)
- **Parakeet Transcription**: 60 minutes audio → 1 second processing
- **Ollama Analysis**: Full transcript → structured summary in ~10 seconds
- **Total Pipeline**: ~1 minute for complete podcast processing

## Architecture

```
RSS → ffmpeg → Parakeet MLX → Ollama → DuckDB → Export
```

- **100% Local Processing** (no API keys required)
- **Apple Silicon Optimized** (MLX framework)
- **High Quality Results** (Parakeet state-of-the-art ASR + Llama3.2)

## Database Schema

- `podcasts`: Feed metadata  
- `episodes`: Downloaded audio files
- `transcripts`: Timestamped segments from Parakeet
- `summaries`: Structured analysis from Ollama (topics, themes, quotes, companies)

## Troubleshooting

- **ffmpeg not found**: `brew install ffmpeg`
- **Parakeet fails**: Falls back to Whisper automatically
- **Ollama connection**: Check `ollama serve` is running
- **Memory issues**: Reduce episodes per feed in config

## Developer Notes

- Added `--force` and `--dry-run` to the `p3 fetch` command (2026-01-19). These flags are handled in `p3/cli.py` and propagated to `PodcastDownloader.fetch_all_feeds()`.
- Re-download behavior updates existing episode rows via `P3Database.update_episode_file_path_by_url(url, file_path, date)` to avoid duplicate `url` entries.
- RSS fetching was made more robust by using `requests.get()` prior to `feedparser.parse()` and by broadening audio detection to `enclosures`, `links` (rel=enclosure), `media_content`, and common audio file extensions.
