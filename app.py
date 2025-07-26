# File: app.py
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import tempfile
import os
import threading
import time
from pathlib import Path
import shutil

app = Flask(__name__)
CORS(app)

# Configuration
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 100)) * 1024 * 1024  # Default 100MB
CLEANUP_INTERVAL = int(os.environ.get('CLEANUP_INTERVAL', 300))  # Default 5 minutes

def cleanup_old_files():
    """Clean up old temporary files"""
    while True:
        try:
            temp_dir = Path(tempfile.gettempdir())
            current_time = time.time()
            
            # Clean up old yt_download directories
            for dir_path in temp_dir.glob("yt_download_*"):
                if dir_path.is_dir() and current_time - dir_path.stat().st_mtime > 3600:  # 1 hour
                    shutil.rmtree(dir_path, ignore_errors=True)
                    
            # Clean up individual temp files
            for file_path in temp_dir.glob("tmp*"):
                if file_path.is_file() and current_time - file_path.stat().st_mtime > 3600:
                    file_path.unlink(missing_ok=True)
                    
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(CLEANUP_INTERVAL)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "YouTube Downloader API v1.0",
        "status": "healthy",
        "endpoints": {
            "GET /": "API information",
            "GET /health": "Health check",
            "POST /api/video-info": "Get video information",
            "POST /api/download": "Download video/audio",
            "POST /api/formats": "Get available formats"
        },
        "usage": {
            "video-info": {
                "method": "POST",
                "body": {"url": "youtube_url"}
            },
            "download": {
                "method": "POST", 
                "body": {"url": "youtube_url", "type": "video|audio", "quality": "best|720p|480p|360p|worst"}
            }
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy", 
        "timestamp": time.time(),
        "uptime": time.time() - start_time,
        "temp_files": len(list(Path(tempfile.gettempdir()).glob("yt_download_*")))
    })

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        url = data.get('url')
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Validate URL format
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({"error": "Please provide a valid YouTube URL"}), 400
        
        print(f"Getting info for: {url}")
        
        # Configure yt-dlp for info extraction only
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_json': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract and clean relevant info
            video_info = {
                'title': info.get('title', 'Unknown').strip(),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown').strip(),
                'view_count': info.get('view_count'),
                'description': (info.get('description', '')[:200] + '...') if info.get('description') else '',
                'thumbnail': info.get('thumbnail'),
                'upload_date': info.get('upload_date'),
                'formats_available': len(info.get('formats', [])),
                'id': info.get('id', ''),
                'webpage_url': info.get('webpage_url', url)
            }
        
        print(f"Successfully extracted info for: {video_info['title']}")
        return jsonify(video_info)
        
    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        print(f"yt-dlp error: {error_msg}")
        return jsonify({"error": f"Video extraction failed: {error_msg}"}), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error: {error_msg}")
        return jsonify({"error": f"Server error: {error_msg}"}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    temp_dir = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        url = data.get('url')
        download_type = data.get('type', 'video')
        quality = data.get('quality', 'best')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Validate URL format
        if not ('youtube.com' in url or 'youtu.be' in url):
            return jsonify({"error": "Please provide a valid YouTube URL"}), 400
        
        print(f"Downloading {download_type} from: {url} (quality: {quality})")
        
        # Create unique temporary directory
        temp_dir = tempfile.mkdtemp(prefix="yt_download_")
        print(f"Using temp directory: {temp_dir}")
        
        # Configure yt-dlp options
        if download_type == 'audio':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
        else:
            # Map quality options with file size limits
            quality_map = {
                'best': 'best[filesize<100M]/best[height<=1080]',
                '720p': 'best[height<=720][filesize<80M]/best[height<=720]',
                '480p': 'best[height<=480][filesize<50M]/best[height<=480]',
                '360p': 'best[height<=360][filesize<30M]/best[height<=360]',
                'worst': 'worst[filesize<20M]/worst'
            }
            
            ydl_opts = {
                'format': quality_map.get(quality, 'best[filesize<100M]/best'),
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
        
        # Download the video/audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
        # Find the downloaded file
        downloaded_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
        
        if not downloaded_files:
            return jsonify({"error": "No file was downloaded. The video might be unavailable or too large."}), 500
        
        # Get the largest file (main download)
        file_sizes = [(f, os.path.getsize(os.path.join(temp_dir, f))) for f in downloaded_files]
        file_sizes.sort(key=lambda x: x[1], reverse=True)
        filename = file_sizes[0][0]
        file_path = os.path.join(temp_dir, filename)
        
        # Check file size
        file_size = os.path.getsize(file_path)
        print(f"Downloaded file: {filename} ({file_size / 1024 / 1024:.2f} MB)")
        
        if file_size > MAX_FILE_SIZE:
            return jsonify({
                "error": f"File too large ({file_size / 1024 / 1024:.1f}MB). Max allowed: {MAX_FILE_SIZE / 1024 / 1024}MB"
            }), 413
        
        # Determine MIME type
        if filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        else:
            mimetype = 'application/octet-stream'
        
        print(f"Sending file: {filename}")
        
        # Send file and schedule cleanup
        def cleanup_later():
            time.sleep(60)  # Wait 1 minute
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                print(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                print(f"Cleanup failed for {temp_dir}: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_later, daemon=True)
        cleanup_thread.start()
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        
    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        print(f"yt-dlp download error: {error_msg}")
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": f"Download failed: {error_msg}"}), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected download error: {error_msg}")
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({"error": f"Server error: {error_msg}"}), 500

@app.route('/api/formats', methods=['POST'])
def get_formats():
    """Get available formats for a video"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        url = data.get('url')
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'listformats': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            seen_formats = set()
            
            for fmt in info.get('formats', []):
                # Create a unique identifier for similar formats
                format_key = (
                    fmt.get('height'),
                    fmt.get('ext'),
                    'video' if fmt.get('vcodec') != 'none' else 'audio'
                )
                
                if format_key not in seen_formats:
                    seen_formats.add(format_key)
                    
                    formats.append({
                        'format_id': fmt.get('format_id'),
                        'ext': fmt.get('ext'),
                        'resolution': fmt.get('resolution', 'audio only' if fmt.get('vcodec') == 'none' else 'unknown'),
                        'height': fmt.get('height'),
                        'filesize': fmt.get('filesize'),
                        'filesize_mb': round(fmt.get('filesize', 0) / 1024 / 1024, 1) if fmt.get('filesize') else None,
                        'vcodec': fmt.get('vcodec'),
                        'acodec': fmt.get('acodec'),
                        'fps': fmt.get('fps'),
                        'type': 'video' if fmt.get('vcodec') != 'none' else 'audio'
                    })
            
            # Sort formats by height (video) and put audio formats at the end
            formats.sort(key=lambda x: (x['type'] == 'audio', -(x['height'] or 0)))
        
        return jsonify({"formats": formats[:20]})  # Limit to 20 formats
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Global variable to track start time
start_time = time.time()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"Starting YouTube Downloader API on port {port}")
    print(f"Max file size: {MAX_FILE_SIZE / 1024 / 1024}MB")
    print(f"Cleanup interval: {CLEANUP_INTERVAL}s")
    
    app.run(host='0.0.0.0', port=port, debug=debug)

