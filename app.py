from flask import Flask, request, jsonify
import json
import requests
import re
from urllib.parse import parse_qs, urlencode
from typing import Dict, Any, List, Optional, Callable

app = Flask(__name__)

# 外部APIのURLを定数として定義 (これが現在動いているデータソース)
EXTERNAL_API_BASE_URL = "https://api-teal-omega.vercel.app/get_data"

# 💡 復号化に必要なJSファイルのURL
PLAYER_JS_URL = "https://pokemogukunnsann.github.io/API-V2/base.js"

# -------------------------------------------------------------
# 1. 署名復号化ヘルパー関数群 (Deciphering Logic)
# -------------------------------------------------------------

# 署名復号化のロジックを格納するキャッシュ
_decipher_cache = {}

def get_decipher_logic(js_url: str) -> Optional[Dict[str, Callable]]:
    """JSコードから復号化のメイン関数とヘルパー関数を抽出・実行可能オブジェクトとして返す"""
    if 'decipher_funcs' in _decipher_cache:
        return _decipher_cache['decipher_funcs']

    try:
        response = requests.get(js_url)
        response.raise_for_status()
        js_code = response.text
    except Exception as e:
        print(f"❌ JSファイルダウンロードエラー: {e}")
        return None

    # 1. ヘルパー関数オブジェクトの抽出
    helper_obj_match = re.search(r'var\s+([a-zA-Z0-9$]+)=\s*\{([\s\S]+?)\};', js_code, re.MULTILINE)
    if not helper_obj_match: return None
        
    helper_obj_name = helper_obj_match.group(1)
    helper_funcs_str = helper_obj_match.group(2)
    
    # 2. メイン復号化関数の操作リストの抽出
    # 署名関数は通常 'a.split("");' で始まり、ヘルパーオブジェクトを呼び出します。
    main_func_match = re.search(
        r'\w+\s*=\s*function\s*\(\s*a\s*\)\s*{\s*a\s*=\s*a\.split\(""\)\s*;\s*((?:[a-zA-Z0-9$]+\.[a-zA-Z0-9$]+\(a,\s*\d+\)\s*;)+)\s*return\s*a\.join\(""\)\s*}', 
        js_code
    )
    if not main_func_match: return None
        
    operations = main_func_match.group(1).split(';')

    # 3. Pythonで実行可能なヘルパー関数を定義
    decipher_funcs: Dict[str, Callable] = {}
    
    def func_splice(arr: list, index: int) -> list: # 配列の先頭から要素を削除
        del arr[:index]
        return arr
        
    def func_reverse(arr: list, *args) -> list: # 配列を反転
        arr.reverse()
        return arr
        
    def func_swap(arr: list, index: int) -> list: # 配列の要素をスワップ
        index = index % len(arr)
        temp = arr[0]
        arr[0] = arr[index]
        arr[index] = temp
        return arr

    # 4. JSコードを解析し、Python関数にマッピング
    
    # splice, reverse, swapの各パターンを抽出
    patterns = {
        'splice': (r'([a-zA-Z0-9$]+):\s*function\(a,b\){a\.splice\(0,b\)}', func_splice),
        'reverse': (r'([a-zA-Z0-9$]+):\s*function\(a\){a\.reverse\(\)}', func_reverse),
        'swap': (r'([a-zA-Z0-9$]+):\s*function\(a,b\){var c=a\[0];a\[0]=a\[b%a\.length];a\[b%a\.length]=c}', func_swap)
    }

    for key, (pattern, func) in patterns.items():
        match = re.search(pattern, helper_funcs_str.replace('\n', '').replace(' ', ''))
        if match:
            # 例: 'b.yG' = func_swap
            decipher_funcs[f"{helper_obj_name}.{match.group(1)}"] = func
    
    _decipher_cache['decipher_funcs'] = decipher_funcs
    _decipher_cache['operations'] = [op.strip() for op in operations if op.strip()]
    
    return _decipher_cache['decipher_funcs']

def decipher_signature(s_cipher: str, js_url: str) -> Optional[str]:
    """暗号化された署名を復号化し、署名文字列を返す"""
    if not get_decipher_logic(js_url):
        return None
        
    decipher_funcs = _decipher_cache['decipher_funcs']
    operations = _decipher_cache['operations']

    signature_array = list(s_cipher)

    for op in operations:
        # 例: b.yG(a, 72)
        func_call = re.match(r'([a-zA-Z0-9$]+\.[a-zA-Z0-9$]+)\(a,\s*(\d+)\)', op)
        if not func_call:
            continue

        func_name = func_call.group(1) # b.yG
        param = int(func_call.group(2)) # 72

        if func_name in decipher_funcs:
            decipher_funcs[func_name](signature_array, param)
    
    return "".join(signature_array)

# -------------------------------------------------------------
# 2. データ整理ヘルパー (既存)
# -------------------------------------------------------------

def extract_stream_info(format_data: Dict[str, Any]) -> Dict[str, Any]:
    """formats または adaptiveFormats から、ストリームURLの基本情報を抽出・整形する。"""
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

# -------------------------------------------------------------
# 3. Flask ルート定義 (データ取得と復号化)
# -------------------------------------------------------------

@app.route("/get_video", methods=['GET'])
def parse_final_api():
    """
    /get_video?id=<VIDEO_ID> で外部APIからデータを取得し、復号化してURLを完成させる。
    """
    video_id = request.args.get('id')
    
    if not video_id:
        return jsonify({"status": "error", "message": "Video ID (id) is required."}), 400

    # 1. 外部APIから生JSONデータを取得
    target_url = f"{EXTERNAL_API_BASE_URL}?id={video_id}"
    
    try:
        response = requests.get(target_url)
        response.raise_for_status()
        innertube_response: Dict[str, Any] = response.json()
        
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "message": f"Failed to fetch data from external API: {e}"}), 502

    # 2. エラーチェック (Bot検出など)
    if innertube_response.get("status") == "error" or innertube_response.get("playabilityStatus", {}).get("status") in ["LOGIN_REQUIRED", "UNPLAYABLE"]:
        return jsonify({"status": "remote_error", "message": "External API or YouTube block detected.", "details": innertube_response}), 403

    # 3. データ整理
    streaming_data = innertube_response.get("streamingData", {})
    all_formats: List[Dict[str, Any]] = streaming_data.get("formats", []) + streaming_data.get("adaptiveFormats", [])
    
    stream_list: List[Dict[str, Any]] = []
    
    for fmt in all_formats:
        stream_info = extract_stream_info(fmt)
        
        # 4. 🔑 復号化ロジックを実行
        if stream_info["is_ciphered"] and stream_info["s_cipher"] and stream_info["url"]:
            
            # デサイファリングを実行！
            deciphered_sig = decipher_signature(stream_info["s_cipher"], PLAYER_JS_URL)
            
            if deciphered_sig:
                # 復号化された署名をURLに追加して完成！
                final_url = f"{stream_info['url']}&{stream_info.get('sp', 'sig')}={deciphered_sig}"
                stream_info["final_playable_url"] = final_url 
                stream_info["is_playable"] = True
            else:
                stream_info["final_playable_url"] = "Deciphering Failed"
        
        stream_list.append(stream_info)

    # 5. 結果を返す
    return jsonify({
        "status": "success",
        "videoId": video_id,
        "videoTitle": innertube_response.get("videoDetails", {}).get("title"),
        "playerJsUrl": PLAYER_JS_URL,
        "stream_count": len(stream_list),
        "streams": stream_list
    })

# -------------------------------------------------------------
# 4. アプリケーション実行
# -------------------------------------------------------------

if __name__ == "__main__":
    app.run(port=5001, debug=True)
