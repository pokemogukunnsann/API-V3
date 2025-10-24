from flask import Flask, request, jsonify
import subprocess
import json
import re
import requests
import shlex
from typing import Dict, Any, Tuple, Optional

# Flaskアプリケーションの初期化
app = Flask(__name__)

# =================================================================
# 1. パラメーター取得機能 (最新の sts/clientVersion を動的に取得)
# =================================================================

def get_latest_innertube_params() -> Tuple[Optional[int], Optional[str]]:
    """
    YouTubeのWebページから最新の sts (signatureTimestamp) と clientVersion を抽出する。
    取得に失敗した場合は、前回成功した静的値をフォールバックとして返す。
    """
    # 以前成功した静的な値をフォールバックとして設定
    FALLBACK_STS = 19800
    FALLBACK_CVER = "2.20251024.00.00"

    try:
        URL = 'https://www.youtube.com/' 
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'
        }
        
        response = requests.get(URL, headers=headers)
        response.raise_for_status()
        html = response.text

        # sts の抽出: "signatureTimestamp":xxxx のパターン
        sts_match = re.search(r'"signatureTimestamp":(\d+)', html)
        latest_sts = int(sts_match.group(1)) if sts_match else None
        
        # clientVersion の抽出: "clientVersion":"x.x.x.x" のパターン
        cver_match = re.search(r'"clientVersion":"([\d\.]+)"', html)
        latest_cver = cver_match.group(1) if cver_match else None
        
        if latest_sts and latest_cver:
            print(f"✅ パラメーター取得成功: sts={latest_sts}, cver={latest_cver}")
            return latest_sts, latest_cver
        
        # 取得できたものが不完全な場合
        print("⚠️ パラメーターの一部が見つかりませんでした。フォールバックを使用します。")
        return FALLBACK_STS, FALLBACK_CVER

    except Exception as e:
        print(f"❌ パラメーター取得エラー: {e}")
        return FALLBACK_STS, FALLBACK_CVER

# =================================================================
# 2. 動画データ取得機能 (成功した curl コマンドを実行)
# =================================================================

def fetch_video_data(video_id: str, sts: int, client_version: str) -> str:
    """
    最新のstsとclientVersionを使ってInnertube APIを呼び出す。
    成功したcurlコマンドの構造を維持するため、subprocessで実行する。
    """
    # 以前の成功コマンドで使った定数
    API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
    VISITOR_DATA = "Cgt0eFNTVThBUHRkNCjK8-rHBjIKCgJVUxIEGgAgTA%3D%3D" # 前回成功した visitorData

    # ペイロードの生成
    payload_dict: Dict[str, Any] = {
        "videoId": video_id,
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version,
                "platform": "DESKTOP",
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
                "gl": "JP",
                "hl": "ja"
            },
            "user": {"lockedSafetyMode": False},
            "visitorData": VISITOR_DATA
        },
        "playbackContext": {"contentPlaybackContext": {"signatureTimestamp": sts}},
        "racyCheckOk": True,
        "contentCheckOk": True
    }

    PAYLOAD_JSON = json.dumps(payload_dict, separators=(',', ':'))

    # curlコマンド文字列を構築
    CURL_COMMAND = (
        f'curl -s -X POST '
        f'"https://www.youtube.com/youtubei/v1/player?key={API_KEY}" '
        f'-H "Accept: */*" '
        f'-H "Accept-Encoding: gzip, deflate" '
        f'-H "Content-Type: application/json" '
        f'-d \'{PAYLOAD_JSON}\' '
        f'--compressed'
    )
    
    try:
        # subprocess.run でコマンド実行
        result = subprocess.run(
            CURL_COMMAND, 
            capture_output=True, 
            text=True, 
            shell=True,
            check=True
        )
        return result.stdout # JSON文字列を返す

    except subprocess.CalledProcessError as e:
        # エラー発生時はエラーJSONを返す
        error_response = {
            "status": "curl_error",
            "message": f"Curl command failed with exit code {e.returncode}",
            "stdout": e.stdout.strip(),
            "stderr": e.stderr.strip()
        }
        return json.dumps(error_response)


# =================================================================
# 3. Flask ルート定義
# =================================================================

@app.route("/get_data")
def get_video_data_api():
    """
    /get_data?id=<VIDEO_ID> でアクセスされたときに動画データを取得するAPIエンドポイント。
    """
    # 1. videoId をクエリパラメーターから取得
    video_id = request.args.get('id')
    
    if not video_id:
        return jsonify({"status": "error", "message": "Video ID (id) is required. Usage: /get_data?id=dQw4w9WgXcQ"}), 400

    # 2. 最新の動的パラメーターを取得
    latest_sts, latest_cver = get_latest_innertube_params()

    # 3. 動的な値を使って API を実行
    api_response_string = fetch_video_data(video_id, latest_sts, latest_cver)

    # 4. レスポンスを JSON として返す
    try:
        # curlの出力をパースして、Flaskのjsonifyで整形して返す
        return jsonify(json.loads(api_response_string))
    except json.JSONDecodeError:
        # JSONとしてパースできなかった場合は、生の出力をエラーとして返す
        return jsonify({"status": "parse_error", "raw_output": api_response_string}), 500

# =================================================================
# 4. アプリケーション実行
# =================================================================

if __name__ == "__main__":
    # 開発サーバーを起動
    app.run(debug=True)
