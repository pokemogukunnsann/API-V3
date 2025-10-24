from flask import Flask, request, jsonify
import json
import requests
import re
from urllib.parse import parse_qs
from typing import Dict, Any, List, Optional, Callable

app = Flask(__name__)

# 外部APIのURLを定数として定義 (現在動いているデータソース)
EXTERNAL_API_BASE_URL = "https://api-teal-omega.vercel.app/get_data"

# 💡 復号化に必要なJSファイルのURL
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

    # 1. ヘルパー関数オブジェクトの抽出 (例: var A={...})
    helper_obj_match = re.search(r'var\s+([a-zA-Z0-9$]+)=\s*\{([\s\S]+?)\};', js_code, re.MULTILINE)
    if not helper_obj_match: 
        print("  [ERROR] ヘルパー関数オブジェクトの抽出に失敗しました。")
        return None
    
    helper_obj_name = helper_obj_match.group(1)
    helper_funcs_str = helper_obj_match.group(2)
    print(f"  [STEP 2-3] ヘルパーオブジェクト名 '{helper_obj_name}' を特定しました。")

    # 2. 🔑 メイン復号化関数の操作リストの抽出 (ロバスト化)
    
    # a. メイン関数の本体を特定
    # パターン: function(a){a=a.split("")...}
    main_func_body_match = re.search(
        r'a\.split\(""\);\s*(.*?);\s*return\s*a\.join\(""\)', 
        js_code, 
        re.DOTALL
    )
    
    if not main_func_body_match: 
        print("  [ERROR] メイン復号化操作リストの抽出に失敗しました。")
        return None
        
    main_func_body = main_func_body_match.group(1)
    print(f"  [DEBUG] メイン関数本体を抽出しました。")
    
    # b. 抽出した関数本体から、ヘルパーオブジェクトを使用した操作呼び出しのみを抽出
    # 操作は `オブジェクト名.関数名(a, パラメータ);` の形式を複数回繰り返す
    operation_list = re.findall(
        re.escape(helper_obj_name)+r'\.[a-zA-Z0-9$]+\(a(?:,\s*\d+)?\)\s*;', 
        main_func_body
    )
    
    if not operation_list:
        print("  [ERROR] 抽出された関数本体から操作リストを特定できませんでした。")
        return None
        
    operations = operation_list

    # 3. Pythonで実行可能なヘルパー関数を定義
    decipher_funcs: Dict[str, Callable] = {}
    
    def func_splice(arr: list, index: int) -> list: del arr[:index]; return arr
    def func_reverse(arr: list, *args) -> list: arr.reverse(); return arr
    def func_swap(arr: list, index: int) -> list:
        if not arr: return arr
        index = index % len(arr)
        temp = arr[0]
        arr[0] = arr[index]
        arr[index] = temp
        return arr

    # 4. JSコードを解析し、Python関数にマッピング
    helper_funcs = re.findall(r'([a-zA-Z0-9$]+)\s*:\s*function\s*\(a(?:,b)?\)\s*\{([\s\S]+?)\}', helper_funcs_str)
    
    patterns_map = {
        'splice': ('a.splice(0,b)', func_splice),
        'reverse': ('a.reverse()', func_reverse),
        'swap': ('var c=a[0];a[0]=a[b%a.length];a[b%a.length]=c', func_swap) 
    }
    
    for func_name, func_body in helper_funcs:
        clean_body = ''.join(func_body.split())
        
        for key, (pattern, func) in patterns_map.items():
            if ''.join(pattern.split()) in clean_body:
                decipher_funcs[f"{helper_obj_name}.{func_name}"] = func
                print(f"  [DEBUG] {key.upper()}関数を '{helper_obj_name}.{func_name}' にマッピングしました。")
                break
    
    _decipher_cache['decipher_funcs'] = decipher_funcs
    # operation_listは既にセミコロン付きなのでそのまま格納
    _decipher_cache['operations'] = [op.strip() for op in operations if op.strip()]
    print(f"  [STEP 2-4] 抽出されたデサイファリング操作の数: {len(_decipher_cache['operations'])} 個")
    print("  [STEP 2-5] 復号化ロジックの解析とキャッシュが完了しました。")
    
    return _decipher_cache['decipher_funcs']

def decipher_signature(s_cipher: str, js_url: str) -> Optional[str]:
    """暗号化された署名を復号化し、署名文字列を返す"""
    print(f"  [STEP 3-1] 署名復号化を開始します。s_cipherの長さ: {len(s_cipher)}")
    if not get_decipher_logic(js_url):
        print("  [ERROR] 復号化ロジックの取得に失敗したため、署名復号化を中断します。")
        return None
        
    decipher_funcs = _decipher_cache['decipher_funcs']
    operations = _decipher_cache['operations']

    signature_array = list(s_cipher)
    op_count = 0
    
    for op in operations:
        # opは "A.b(a,3);" のような文字列
        func_call = re.match(r'([a-zA-Z0-9$]+\.[a-zA-Z0-9$]+)\(a\s*(?:,\s*(\d+))?\)', op)
        
        if not func_call:
            continue

        func_name = func_call.group(1)
        param_str = func_call.group(2)
        param = int(param_str) if param_str else 0 

        if func_name in decipher_funcs:
            print(f"  [DEBUG] 適用操作: {func_name}, パラメータ: {param}, 配列の長さ: {len(signature_array)}")
            
            decipher_funcs[func_name](signature_array, param)
            op_count += 1
    
    deciphered_sig = "".join(signature_array)
    print(f"  [STEP 3-2] 復号化操作を {op_count} 回適用しました。")
    print(f"  [STEP 3-3] 復号化された署名 (sig) の長さ: {len(deciphered_sig)}")
    
    return deciphered_sig

# -------------------------------------------------------------
# 2. データ整理ヘルパー (変更なし)
# -------------------------------------------------------------

def extract_stream_info(format_data: Dict[str, Any]) -> Dict[str, Any]:
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
# 3. Flask ルート定義 (変更なし)
# -------------------------------------------------------------

@app.route("/parse_final", methods=['GET'])
def parse_final_api():
    video_id = request.args.get('id')
    
    if not video_id:
        print("[ERROR] Video IDが指定されていません。")
        return jsonify({"status": "error", "message": "Video ID (id) is required."}), 400

    print(f"==================================================")
    print(f"[START] 処理開始: Video ID = {video_id}")
    
    target_url = f"{EXTERNAL_API_BASE_URL}?id={video_id}"
    print(f"[STEP 1-1] 🚀 外部APIへデータ取得リクエスト: {target_url}")
    
    try:
        response = requests.get(target_url)
        response.raise_for_status()
        innertube_response: Dict[str, Any] = response.json()
        
        # ご要望のprint文
        print(f"レスポンス: {response}")
        print(f"Innertubeレスポンス (JSON): {json.dumps(innertube_response, indent=2)}")
        
        print("[STEP 1-2] 外部APIからのデータ取得成功。JSONを解析します。")
        
    except requests.exceptions.RequestException as e:
        print(f"[FATAL] 外部APIからのデータ取得中にエラーが発生: {e}")
        return jsonify({"status": "error", "message": f"Failed to fetch data from external API: {e}"}), 502

    status = innertube_response.get("playabilityStatus", {}).get("status")
    if status in ["LOGIN_REQUIRED", "UNPLAYABLE"]:
        print(f"[BLOCK] ⚠️ YouTubeブロック検出: status={status}")
        return jsonify({"status": "remote_error", "message": "External API or YouTube block detected.", "details": innertube_response}), 403

    streaming_data = innertube_response.get("streamingData", {})
    all_formats: List[Dict[str, Any]] = streaming_data.get("formats", []) + streaming_data.get("adaptiveFormats", [])
    
    print(f"[STEP 1-3] ストリーム情報を整理します。合計 {len(all_formats)} 個のフォーマットが見つかりました。")
    
    stream_list: List[Dict[str, Any]] = []
    
    for i, fmt in enumerate(all_formats):
        stream_info = extract_stream_info(fmt)
        
        if stream_info["is_ciphered"] and stream_info["s_cipher"] and stream_info["url"]:
            print(f"[STREAM {i+1}] 🔐 暗号化されたストリームです (itag: {stream_info['itag']})。復号化が必要です...")
            
            deciphered_sig = decipher_signature(stream_info["s_cipher"], PLAYER_JS_URL)
            
            if deciphered_sig:
                final_url = f"{stream_info['url']}&{stream_info.get('sp', 'sig')}={deciphered_sig}"
                stream_info["final_playable_url"] = final_url 
                stream_info["is_playable"] = True
                print(f"[STREAM {i+1}] ✅ 復号化成功！最終URLが生成されました。")
            else:
                stream_info["final_playable_url"] = "Deciphering Failed"
                print(f"[STREAM {i+1}] ❌ 復号化に失敗しました。")
        
        elif stream_info["url"]:
            stream_info["final_playable_url"] = stream_info["url"]
            stream_info["is_playable"] = True
            print(f"[STREAM {i+1}] 🟢 再生可能なURLが直接提供されています (itag: {stream_info['itag']})。")
        
        stream_list.append(stream_info)

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
