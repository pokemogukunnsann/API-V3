from flask import Flask, request, jsonify
import json
import requests
import re
from urllib.parse import parse_qs
from typing import Dict, Any, List, Optional, Callable

app = Flask(__name__)

# 外部APIのURLを定数として定義 (現在動いているデータソース)
EXTERNAL_API_BASE_URL = "https://api-teal-omega.vercel.app/get_data"

# 💡 復号化に必要なJSファイルのURL (あなたが特定したURL)
PLAYER_JS_URL = "https://pokemogukunnsann.github.io/API-V2/base.js"

# -------------------------------------------------------------
# 1. 署名復号化ヘルパー関数群 (Deciphering Logic)
# -------------------------------------------------------------

_decipher_cache = {}

def get_decipher_logic(js_url: str) -> Optional[Dict[str, Callable]]:
    """JSコードから復号化のメイン関数とヘルパー関数を抽出・実行可能オブジェクトとして返す"""
    print(f"  [DEBUG] 復号化ロジックキャッシュ確認中...")
    if 'decipher_funcs' in _decipher_cache:
        print("  [DEBUG] 復号化ロジックはキャッシュに存在します。")
        return _decipher_cache['decipher_funcs']

    print(f"  [STEP 2-1] 🔑 JSファイルダウンロード開始: {js_url}")
    try:
        response = requests.get(js_url)
        response.raise_for_status()
        js_code = response.text
        print("  [STEP 2-2] JSファイルダウンロード成功。解析を開始します。")
    except Exception as e:
        print(f"  [ERROR] JSファイルダウンロードエラー: {e}")
        return None

    # 1. ヘルパー関数オブジェクトの抽出 (例: var b={...})
    helper_obj_match = re.search(r'var\s+([a-zA-Z0-9$]+)=\s*\{([\s\S]+?)\};', js_code, re.MULTILINE)
    if not helper_obj_match: 
        print("  [ERROR] ヘルパー関数オブジェクトの抽出に失敗しました。")
        return None
    
    helper_obj_name = helper_obj_match.group(1)
    helper_funcs_str = helper_obj_match.group(2)
    print(f"  [STEP 2-3] ヘルパーオブジェクト名 '{helper_obj_name}' を特定しました。")
    
    # 2. メイン復号化関数の操作リストの抽出
    main_func_match = re.search(
        r'\w+\s*=\s*function\s*\(\s*a\s*\)\s*{\s*a\s*=\s*a\.split\(""\)\s*;\s*((?:[a-zA-Z0-9$]+\.[a-zA-Z0-9$]+\(a,\s*\d+\)\s*;)+)\s*return\s*a\.join\(""\)\s*}', 
        js_code
    )
    if not main_func_match: 
        print("  [ERROR] メイン復号化操作リストの抽出に失敗しました。")
        return None
        
    operations = main_func_match.group(1).split(';')

    # 3. Pythonで実行可能なヘルパー関数を定義 (省略: 定義済みのものを再利用)

    # 4. JSコードを解析し、Python関数にマッピング
    decipher_funcs: Dict[str, Callable] = {}
    
    def func_splice(arr: list, index: int) -> list: del arr[:index]; return arr
    def func_reverse(arr: list, *args) -> list: arr.reverse(); return arr
    def func_swap(arr: list, index: int) -> list:
        index = index % len(arr)
        temp = arr[0]
        arr[0] = arr[index]
        arr[index] = temp
        return arr
    
    patterns = {
        'splice': (r'([a-zA-Z0-9$]+):\s*function\(a,b\){a\.splice\(0,b\)}', func_splice),
        'reverse': (r'([a-zA-Z0-9$]+):\s*function\(a\){a\.reverse\(\)}', func_reverse),
        'swap': (r'([a-zA-Z0-9$]+):\s*function\(a,b\){var c=a\[0];a\[0]=a\[b%a\.length];a\[b%a\.length]=c}', func_swap)
    }

    print(f"  [STEP 2-4] 抽出されたデサイファリング操作の数: {len([op.strip() for op in operations if op.strip()])} 個")
    
    for key, (pattern, func) in patterns.items():
        match = re.search(pattern, helper_funcs_str.replace('\n', '').replace(' ', ''))
        if match:
            decipher_funcs[f"{helper_obj_name}.{match.group(1)}"] = func
            print(f"  [DEBUG] {key.upper()}関数を '{helper_obj_name}.{match.group(1)}' にマッピングしました。")
    
    _decipher_cache['decipher_funcs'] = decipher_funcs
    _decipher_cache['operations'] = [op.strip() for op in operations if op.strip()]
    print("  [STEP 2-5] 復号化ロジックの解析とキャッシュが完了しました。")
    
    return _decipher_cache['decipher_funcs']

def decipher_signature(s_cipher: str, js_url: str) -> Optional[str]:
    """暗号化された署名を復号化し、署名文字列を返す"""
    print(f"  [STEP 3-1] 署名復号化を開始します。s_cipherの長さ: {len(s_cipher)}")
    if not get_decipher_logic(js_url):
        return None
        
    decipher_funcs = _decipher_cache['decipher_funcs']
    operations = _decipher_cache['operations']

    signature_array = list(s_cipher)
    op_count = 0
    
    for op in operations:
        func_call = re.match(r'([a-zA-Z0-9$]+\.[a-zA-Z0-9$]+)\(a,\s*(\d+)\)', op)
        if not func_call:
            continue

        func_name = func_call.group(1)
        param = int(func_call.group(2))

        if func_name in decipher_funcs:
            decipher_funcs[func_name](signature_array, param)
            op_count += 1
    
    deciphered_sig = "".join(signature_array)
    print(f"  [STEP 3-2] 復号化操作を {op_count} 回適用しました。")
    print(f"  [STEP 3-3] 復号化された署名 (sig) の長さ: {len(deciphered_sig)}")
    
    return deciphered_sig

# -------------------------------------------------------------
# 2. データ整理ヘルパー (既存)
# -------------------------------------------------------------

def extract_stream_info(format_data: Dict[str, Any]) -> Dict[str, Any]:
    # ... (前回の extract_stream_info 関数と同一) ...
    stream_info: Dict[str, Any] = {
        "itag": format_data.get("itag"),
        "mimeType": format_data.get("mimeType"),
        "qualityLabel": format_data.get("qualityLabel", format_data.get("quality")),
        "is_ciphered": False,
        "is_playable": False,
        "url": None,
        "s_cipher": None 
    }

    if "url" in format_data and "sig" in format_data["url"]:
        stream_info["url"] = format_data["url"]
        stream_info["is_playable"] = True
    elif "url" in format_data:
        stream_info["url"] = format_data["url"]

    if "signatureCipher" in format_data:
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
    video_id = request.args.get('id')
    
    if not video_id:
        print("[ERROR] Video IDが指定されていません。")
        return jsonify({"status": "error", "message": "Video ID (id) is required."}), 400

    print(f"==================================================")
    print(f"[START] 処理開始: Video ID = {video_id}")
    
    # 1. 外部APIから生JSONデータを取得
    target_url = f"{EXTERNAL_API_BASE_URL}?id={video_id}"
    print(f"[STEP 1-1] 🚀 外部APIへデータ取得リクエスト: {target_url}")
    
    try:
        response = requests.get(target_url)
        response.raise_for_status()
        innertube_response: Dict[str, Any] = response.json()
        print("[STEP 1-2] 外部APIからのデータ取得成功。JSONを解析します。")
        print(f"レスポンス:{response}")
        
    except requests.exceptions.RequestException as e:
        print(f"[FATAL] 外部APIからのデータ取得中にエラーが発生: {e}")
        return jsonify({"status": "error", "message": f"Failed to fetch data from external API: {e}"}), 502

    # 2. エラーチェック (Bot検出など)
    status = innertube_response.get("playabilityStatus", {}).get("status")
    if status in ["LOGIN_REQUIRED", "UNPLAYABLE"]:
        print(f"[BLOCK] ⚠️ YouTubeブロック検出: status={status}")
        return jsonify({"status": "remote_error", "message": "External API or YouTube block detected.", "details": innertube_response}), 403

    # 3. データ整理
    streaming_data = innertube_response.get("streamingData", {})
    all_formats: List[Dict[str, Any]] = streaming_data.get("formats", []) + streaming_data.get("adaptiveFormats", [])
    
    print(f"[STEP 1-3] ストリーム情報を整理します。合計 {len(all_formats)} 個のフォーマットが見つかりました。")
    
    stream_list: List[Dict[str, Any]] = []
    
    for i, fmt in enumerate(all_formats):
        stream_info = extract_stream_info(fmt)
        
        # 4. 🔑 復号化ロジックを実行
        if stream_info["is_ciphered"] and stream_info["s_cipher"] and stream_info["url"]:
            print(f"[STREAM {i+1}] 🔐 暗号化されたストリームです (itag: {stream_info['itag']})。復号化が必要です...")
            
            # デサイファリングを実行！
            deciphered_sig = decipher_signature(stream_info["s_cipher"], PLAYER_JS_URL)
            
            if deciphered_sig:
                # 復号化された署名をURLに追加して完成！
                final_url = f"{stream_info['url']}&{stream_info.get('sp', 'sig')}={deciphered_sig}"
                stream_info["final_playable_url"] = final_url 
                stream_info["is_playable"] = True
                print(f"[STREAM {i+1}] ✅ 復号化成功！最終URLが生成されました。")
            else:
                stream_info["final_playable_url"] = "Deciphering Failed"
                print(f"[STREAM {i+1}] ❌ 復号化に失敗しました。")
        
        # 署名が必要ないストリームも、最終URLとしてそのまま格納
        elif stream_info["url"] and stream_info["is_playable"]:
            stream_info["final_playable_url"] = stream_info["url"]
            print(f"[STREAM {i+1}] 🟢 再生可能なURLが直接提供されています (itag: {stream_info['itag']})。")
        
        stream_list.append(stream_info)

    # 5. 結果を返す
    print(f"[END] 処理完了。{len(stream_list)}個のストリーム情報を返します。")
    print(f"==================================================")
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
