from flask import Flask, request, jsonify
import subprocess
import json
import re
import requests
from urllib.parse import parse_qs
from typing import Dict, Any, List, Tuple, Optional

app = Flask(__name__)

# 以前成功した静的な値をフォールバックとして設定
FALLBACK_STS = 19800
FALLBACK_CVER = "2.20251024.00.00"
API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
# 🚨 注意: この visitorData は依然として Bot 検出の原因となるため、将来的には動的取得が必要です。
VISITOR_DATA = "Cgt0eFNTVThBUHRkNCjK8-rHBjIKCgJVUxIEGgAgTA%3D%3D" 

# =================================================================
# 1. パラメーター取得機能 (外部APIからこちらに移動)
# =================================================================

def get_latest_innertube_params() -> Tuple[Optional[int], Optional[str]]:
    """YouTubeの動画ページから最新の sts と clientVersion を抽出する。"""
    try:
        URL = 'https://www.youtube.com/' 
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'}
        response = requests.get(URL, headers=headers)
        response.raise_for_status()
        html = response.text

        sts_match = re.search(r'"signatureTimestamp":(\d+)', html)
        latest_sts = int(sts_match.group(1)) if sts_match else None
        
        cver_match = re.search(r'"clientVersion":"([\d\.]+)"', html)
        latest_cver = cver_match.group(1) if cver_match else None
        
        if latest_sts and latest_cver:
            return latest_sts, latest_cver
        
        return FALLBACK_STS, FALLBACK_CVER

    except Exception as e:
        print(f"❌ パラメーター取得エラー: {e}")
        return FALLBACK_STS, FALLBACK_CVER

# =================================================================
# 2. 動画データ取得機能 (外部APIからこちらに移動)
# =================================================================

def fetch_video_data(video_id: str, sts: int, client_version: str) -> str:
    """最新のstsとclientVersionを使ってInnertube APIを実行し、結果を返す。"""
    
    payload_dict: Dict[str, Any] = {
        "videoId": video_id,
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version,
                "platform": "DESKTOP",
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36",
                "gl": "JP", "hl": "ja"
            },
            "user": {"lockedSafetyMode": False},
            "visitorData": VISITOR_DATA
        },
        "playbackContext": {"contentPlaybackContext": {"signatureTimestamp": sts}},
        "racyCheckOk": True,
        "contentCheckOk": True
    }

    PAYLOAD_JSON = json.dumps(payload_dict, separators=(',', ':'))

    # 以前成功した curl コマンドを subprocess で実行
    CURL_COMMAND = (
        f'curl -s -X POST '
        f'"https://www.youtube.com/youtubei/v1/player?key={API_KEY}" '
        f'-H "Accept: */*" -H "Accept-Encoding: gzip, deflate" '
        f'-H "Content-Type: application/json" '
        f'-d \'{PAYLOAD_JSON}\' '
        f'--compressed'
    )
    
    try:
        result = subprocess.run(
            CURL_COMMAND, capture_output=True, text=True, shell=True, check=True
        )
        return result.stdout

    except subprocess.CalledProcessError as e:
        error_response = {"status": "curl_error", "message": "Failed to execute curl"}
        return json.dumps(error_response)
        
# =================================================================
# 3. データ整理ヘルパー (既存)
# =================================================================

def extract_stream_info(format_data: Dict[str, Any]) -> Dict[str, Any]:
    # ... (前回の extract_stream_info 関数をそのまま使用) ...
    stream_info: Dict[str, Any] = {
        "itag": format_data.get("itag"),
        "mimeType": format_data.get("mimeType"),
        "qualityLabel": format_data.get("qualityLabel", format_data.get("quality")),
        "is_ciphered": False,
        "is_playable": False,
        "url": None,
        "s_cipher": None 
    }

    if "url" in format_data:
        stream_info["url"] = format_data["url"]
        stream_info["is_playable"] = True

    elif "signatureCipher" in format_data:
        stream_info["is_ciphered"] = True
        cipher_params = parse_qs(format_data["signatureCipher"])
        
        base_url = cipher_params.get("url", [None])[0]
        if base_url:
            stream_info["url"] = base_url
            
        stream_info["s_cipher"] = cipher_params.get("s", [None])[0]
        stream_info["sp"] = cipher_params.get("sp", ["sig"])[0]

    stream_info["container"] = stream_info["mimeType"].split(";")[0].split("/")[-1]
    stream_info["vcodec"] = format_data.get("vcodec")
    stream_info["acodec"] = format_data.get("acodec")
    return stream_info

def extract_player_js_url(innertube_response: Dict[str, Any]) -> str | None:
    # ... (前回の extract_player_js_url 関数をそのまま使用) ...
    # 簡略化のため、提供されたURLを固定で返すようにする。
    # 🚨 本来は生JSONから探す必要がありますが、デバッグを優先し、カカオマメさんが見つけたURLを使用します。
    # return "https://www.youtube.com/yts/jsbin/player-v20251024-web-l10n_ja_JP.js" # 生JSONで見つけるべきもの
    
    # 💡 復号化ロジックのURLが分かっているので、これを使います！
    return "https://pokemogukunnsann.github.io/API-V2/base.js" 
    
# ※ get_decipher_logic は、デバッグ後の最終段階で組み込みます。

# =================================================================
# 4. Flask ルート定義 (統合)
# =================================================================

@app.route("/get_video", methods=['GET'])
def get_video_data_api():
    """
    /get_video?id=<VIDEO_ID> で全処理を実行する。
    """
    video_id = request.args.get('id')
    
    if not video_id:
        return jsonify({"status": "error", "message": "Video ID (id) is required."}), 400

    # 1. 最新の動的パラメーターを取得
    latest_sts, latest_cver = get_latest_innertube_params()
    
    # 2. 動画データ取得機能を実行
    api_response_string = fetch_video_data(video_id, latest_sts, latest_cver)

    try:
        innertube_response: Dict[str, Any] = json.loads(api_response_string)
    except json.JSONDecodeError:
        return jsonify({"status": "error", "message": "Failed to decode Innertube API response."}), 500

    # 3. Bot検出によるエラーチェック
    if innertube_response.get("playabilityStatus", {}).get("status") in ["LOGIN_REQUIRED", "UNPLAYABLE"]:
        return jsonify({"status": "bot_detected", "message": "YouTube detected bot activity. Try restarting the script or changing IP/User-Agent.", "details": innertube_response}), 403

    # 4. データ整理とJS URL抽出
    player_js_full_url = extract_player_js_url(innertube_response) # 💡 URLを固定値で取得

    streaming_data = innertube_response.get("streamingData", {})
    all_formats: List[Dict[str, Any]] = streaming_data.get("formats", []) + streaming_data.get("adaptiveFormats", [])

    stream_list: List[Dict[str, Any]] = [extract_stream_info(fmt) for fmt in all_formats]

    # 5. 結果を返す
    return jsonify({
        "status": "success",
        "videoId": video_id,
        "videoTitle": innertube_response.get("videoDetails", {}).get("title"),
        "playerJsUrl": player_js_full_url,
        "stream_count": len(stream_list),
        "streams": stream_list
    })

# =================================================================
# 5. アプリケーション実行
# =================================================================

if __name__ == "__main__":
    # サーバーを起動
    app.run(port=5001, debug=True)
