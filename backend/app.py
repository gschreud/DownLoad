# app.py - Flask backend for Render deployment
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import tempfile
import os
import threading
import time
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Store for tracking downloads
downloads = {}

def cleanup_old_files():
    """Clean up old temporary files"""
    while True:
        try:
            temp_dir = Path(tempfile.gettempdir())
            current_time = time.time()
            
            for file_path in temp_dir.glob("yt_download_*"):
                if current_time - file_path.stat().st_mtime > 3600:  # 1 hour
                    file_path.unlink(missing_ok=True)
        except:
            pass
        time.sleep(300)  # Clean every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "YouTube Downloader API",
        "endpoints": {
            "POST /api/video-info": "Get video information",
            "POST /api/download": "Download video/audio",
            "GET /health": "Health check"
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "timestamp": time.time()})

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Configure yt-dlp for info extraction only
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract relevant info
            video_info = {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count'),
                'description': (info.get('description', '')[:200] + '...') if info.get('description') else '',
                'thumbnail': info.get('thumbnail'),
                'upload_date': info.get('upload_date'),
                'formats_available': len(info.get('formats', []))
            }
        
        return jsonify(video_info)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        download_type = data.get('type', 'video')
        quality = data.get('quality', 'best')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Create unique temporary file
        temp_dir = tempfile.mkdtemp(prefix="yt_download_")
        
        try:
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
                # Map quality options
                quality_map = {
                    'best': 'best[filesize<50M]/best',
                    '720p': 'best[height<=720][filesize<50M]/best[height<=720]',
                    '480p': 'best[height<=480][filesize<50M]/best[height<=480]',
                    '360p': 'best[height<=360][filesize<50M]/best[height<=360]',
                    'worst': 'worst'
                }
                
                ydl_opts = {
                    'format': quality_map.get(quality, 'best[filesize<50M]/best'),
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
                return jsonify({"error": "No file was downloaded"}), 500
            
            file_path = os.path.join(temp_dir, downloaded_files[0])
            filename = downloaded_files[0]
            
            # Check file size (limit to reasonable size for web download)
            file_size = os.path.getsize(file_path)
            if file_size > 100 * 1024 * 1024:  # 100MB limit
                return jsonify({"error": "File too large for web download"}), 413
            
            # Send file
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/octet-stream'
            )
            
        finally:
            # Schedule cleanup of temp directory after a delay
            def cleanup_later():
                time.sleep(60)  # Wait 1 minute
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
            
            cleanup_thread = threading.Thread(target=cleanup_later, daemon=True)
            cleanup_thread.start()
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/formats', methods=['POST'])
def get_formats():
    """Get available formats for a video"""
    try:
        data = request.get_json()
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
            for fmt in info.get('formats', []):
                if fmt.get('vcodec') != 'none' or fmt.get('acodec') != 'none':
                    formats.append({
                        'format_id': fmt.get('format_id'),
                        'ext': fmt.get('ext'),
                        'resolution': fmt.get('resolution', 'audio only' if fmt.get('vcodec') == 'none' else 'unknown'),
                        'filesize': fmt.get('filesize'),
                        'vcodec': fmt.get('vcodec'),
                        'acodec': fmt.get('acodec'),
                    })
        
        return jsonify({"formats": formats})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

# requirements.txt for Render
# yt-dlp==2023.12.30
# flask==2.3.3
# flask-cors==4.0.0
# gunicorn==21.2.0
# certifi

# Procfile for Render
# web: gunicorn app:app