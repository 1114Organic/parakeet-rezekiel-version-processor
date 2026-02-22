"""Podcast episode downloader and RSS feed processor."""

import os
import requests
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse
import feedparser
from functools import wraps
# from pydub import AudioSegment  # Disabled due to Python 3.13 compatibility
import subprocess
import tempfile

from .database import P3Database

# Configure logging
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handler (logs all messages)
fh = logging.FileHandler(LOG_DIR / "downloader.log")
fh.setLevel(logging.DEBUG)

# Console handler (logs info and above)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)


def retry_with_backoff(max_attempts: int = 3, base_delay: float = 1.0):
    """Decorator for retrying functions with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(f"Max retries ({max_attempts}) exceeded for {func.__name__}: {e}")
                        raise
                    
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator


class PodcastDownloader:
    def __init__(self, db: P3Database, data_dir: str = "data", 
                 max_episodes: int = 10, audio_format: str = "wav"):
        self.db = db
        self.data_dir = Path(data_dir)
        self.audio_dir = self.data_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.max_episodes = max_episodes
        self.audio_format = audio_format

    def add_feed(self, name: str, url: str, category: str = None) -> int:
        """Add a new podcast feed to the database."""
        existing = self.db.get_podcast_by_url(url)
        if existing:
            return existing["id"]
        return self.db.add_podcast(name, url, category)

    @retry_with_backoff(max_attempts=3, base_delay=2.0)
    def fetch_episodes(self, rss_url: str, limit: int = None) -> List[Dict]:
        """Fetch episode metadata from RSS feed with retry logic.
        
        Args:
            rss_url: RSS feed URL
            limit: Max episodes to fetch
            
        Returns:
            List of episode metadata dicts
            
        Raises:
            Exception: If all retry attempts fail
        """
        if limit is None:
            limit = self.max_episodes

        try:
            # Fetch the feed content via requests first to avoid issues some
            # servers present when parsed directly from URL.
            logger.debug(f"Fetching RSS feed: {rss_url}")
            resp = requests.get(rss_url, timeout=30)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            episodes = []
            
            for entry in feed.entries[:limit]:
                # Find audio enclosure or link. Broaden detection to handle
                # enclosures, links (rel=enclosure), media_content, and
                # fall back to entry.link when it looks like an audio file.
                audio_url = None
                audio_exts = ('.mp3', '.m4a', '.aac', '.wav', '.ogg', '.opus', '.flac', '.mp4')

                # 1) Check explicit enclosures
                for enclosure in entry.get('enclosures', []):
                    href = enclosure.get('href') if hasattr(enclosure, 'get') else getattr(enclosure, 'href', None)
                    typ = enclosure.get('type') if hasattr(enclosure, 'get') else getattr(enclosure, 'type', None)
                    if not href:
                        continue
                    if (typ and 'audio' in typ) or href.lower().endswith(audio_exts):
                        audio_url = href
                        break

                # 2) Check generic links (some feeds put enclosure info here)
                if not audio_url:
                    for link in entry.get('links', []):
                        href = link.get('href') if hasattr(link, 'get') else getattr(link, 'href', None)
                        rel = link.get('rel') if hasattr(link, 'get') else getattr(link, 'rel', None)
                        typ = link.get('type') if hasattr(link, 'get') else getattr(link, 'type', None)
                        if not href:
                            continue
                        if (rel and rel == 'enclosure') or (typ and 'audio' in typ) or href.lower().endswith(audio_exts):
                            audio_url = href
                            break

                # 3) Check media_content (media RSS)
                if not audio_url:
                    for media in entry.get('media_content', []):
                        href = media.get('url') if hasattr(media, 'get') else getattr(media, 'url', None)
                        typ = media.get('type') if hasattr(media, 'get') else getattr(media, 'type', None)
                        if not href:
                            continue
                        if (typ and 'audio' in typ) or href.lower().endswith(audio_exts):
                            audio_url = href
                            break

                # 4) Fallback to entry.link if it points to an audio file
                if not audio_url:
                    link_href = entry.get('link')
                    if link_href and isinstance(link_href, str) and link_href.lower().endswith(audio_exts):
                        audio_url = link_href

                if not audio_url:
                    continue

                # Parse publication date
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                episodes.append({
                    'title': entry.get('title', 'Unknown Title'),
                    'url': audio_url,
                    'date': pub_date,
                    'description': entry.get('description', ''),
                    'guid': entry.get('id', audio_url)
                })
            
            return episodes
            
        except Exception as e:
            logger.error(f"Error fetching RSS feed {rss_url}: {e}")
            raise  # Let the retry decorator handle retries

    @retry_with_backoff(max_attempts=3, base_delay=2.0)
    def download_episode(self, episode_url: str, filename: str) -> Optional[str]:
        """Download and normalize audio episode with retry logic.
        
        Args:
            episode_url: URL of episode audio file
            filename: Filename for saving
            
        Returns:
            Path to downloaded file, or None if failed
        """
        try:
            logger.debug(f"Downloading episode: {filename}")
            # Download audio file
            response = requests.get(episode_url, stream=True, timeout=300)
            response.raise_for_status()
            
            # Save to temporary file first
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name

            # Convert and normalize with ffmpeg
            output_path = self.audio_dir / f"{filename}.{self.audio_format}"
            
            # Use ffmpeg for reliable audio processing and normalization
            cmd = [
                'ffmpeg', '-y',  # overwrite existing files
                '-i', tmp_path,
                '-ar', '16000',  # 16kHz sample rate for Whisper
                '-ac', '1',      # mono
                '-c:a', 'pcm_s16le' if self.audio_format == 'wav' else 'libmp3lame',
                '-af', 'loudnorm',  # normalize audio levels
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"FFmpeg error: {result.stderr}")
                # Fallback to pydub
                return self._fallback_conversion(tmp_path, output_path)
            
            # Clean up temp file
            os.unlink(tmp_path)
            
            return str(output_path)
            
        except Exception as e:
            print(f"Error downloading {episode_url}: {e}")
            return None

    def _fallback_conversion(self, input_path: str, output_path: Path) -> str:
        """Fallback audio conversion using ffmpeg directly."""
        try:
            # Use ffmpeg without pydub as fallback
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-ar', '16000', '-ac', '1',
                str(output_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                os.unlink(input_path)
                return str(output_path)
            else:
                logger.error(f"FFmpeg conversion failed for {filename}: {result.stderr}")
                os.unlink(input_path)
                return None
            
        except Exception as e:
            logger.error(f"Error downloading episode {filename}: {e}")
            raise  # Let the retry decorator handle retries

    def process_feed(self, rss_url: str, force: bool = False, dry_run: bool = False) -> int:
        """Process a single RSS feed and download new episodes.

        If `force` is True, existing episodes (matched by URL) will be
        re-downloaded and their `file_path` updated in the database.
        """
        podcast = self.db.get_podcast_by_url(rss_url)
        if not podcast:
            print(f"Podcast not found for URL: {rss_url}")
            return 0

        episodes = self.fetch_episodes(rss_url)
        downloaded_count = 0
        
        for ep_data in episodes:
            # Check whether episode exists
            exists = self.db.episode_exists(ep_data['url'])
            if exists and not force:
                continue

            if exists and force:
                action_msg = f"Would re-download: {ep_data['title']}" if dry_run else f"Re-downloading: {ep_data['title']}"
            else:
                action_msg = f"Would download: {ep_data['title']}" if dry_run else f"Downloading: {ep_data['title']}"

            print(action_msg)

            if dry_run:
                # In dry-run mode, don't perform network I/O or DB writes; just report
                downloaded_count += 1
                continue

            # Generate safe filename
            safe_title = "".join(c for c in ep_data['title'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"{podcast['id']}_{safe_title[:50]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Download episode
            file_path = self.download_episode(ep_data['url'], filename)
            if file_path:
                # Add or update database record
                if exists:
                    # Update existing episode record with new file path (re-download)
                    self.db.update_episode_file_path_by_url(ep_data['url'], file_path, ep_data['date'])
                else:
                    self.db.add_episode(
                        podcast_id=podcast['id'],
                        title=ep_data['title'],
                        date=ep_data['date'],
                        url=ep_data['url'],
                        file_path=file_path
                    )
                downloaded_count += 1
                print(f"✓ Downloaded: {ep_data['title']}")
            else:
                print(f"✗ Failed to download: {ep_data['title']}")
        
        return downloaded_count

    def fetch_all_feeds(self, feeds_config: List[Dict], force: bool = False, dry_run: bool = False) -> Dict[str, int]:
        """Process all configured RSS feeds with error isolation and rate limiting.

        `force` is a global override to re-download existing episodes.
        `dry_run` when True will only report actions without network I/O or DB writes.
        
        Feed-level errors are caught and logged; processing continues for other feeds.
        Rate limiting: 1 second delay between feeds to avoid IP blocking.
        """
        results = {}
        failed_feeds = []

        for feed_config in feeds_config:
            name = feed_config['name']
            url = feed_config['url']
            category = feed_config.get('category')
            # Per-feed force/dry_run options override global flags
            feed_force = feed_config.get('force', force)
            feed_dry_run = feed_config.get('dry_run', dry_run)
            
            try:
                logger.info(f"Processing feed: {name}")

                # Ensure podcast exists in database
                self.add_feed(name, url, category)

                # Process episodes
                count = self.process_feed(url, force=feed_force, dry_run=feed_dry_run)
                results[name] = count
                logger.info(f"Downloaded {count} new episodes from {name}")
                
            except Exception as e:
                logger.error(f"Error processing feed '{name}' ({url}): {e}", exc_info=True)
                failed_feeds.append(name)
                results[name] = 0
            
            # Rate limiting: 1 second delay between feeds to avoid IP blocking
            time.sleep(1)
        
        if failed_feeds:
            logger.warning(f"Failed to process {len(failed_feeds)} feed(s): {', '.join(failed_feeds)}")

        return results
