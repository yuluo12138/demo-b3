import json
import datetime
import uuid
import os
import re
import math # math 模块在您提供的代码中没有直接用到，但保留以防后续扩展
from flask import Flask, request, jsonify, render_template, abort, url_for
from urllib.parse import quote_plus # 同上，保留以防后续扩展
from collections import defaultdict
import binascii

app = Flask(__name__)

# --- 配置 ---
DATA_FILE = 'data_store.json'
DATA_STORE = {} # 存储原始的 message_entry: {raw_post_data, parsed_content, receive_time}

# 高德地图JS API Key
AMAP_JSAPI_KEY = '9374c8276711715a3e4a6b5180e8ca63'


# --- 数据持久化辅助函数 ---
def load_data():
    """从文件中加载数据到 DATA_STORE"""
    global DATA_STORE
    print(f"[{datetime.datetime.now()}] [INFO] 尝试从 {DATA_FILE} 加载数据...")
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                if not isinstance(loaded_data, dict):
                    raise ValueError("加载的数据不是字典格式。")
                DATA_STORE = loaded_data
            
            for id_num, messages in DATA_STORE.items():
                if not isinstance(messages, list):
                    print(f"[{datetime.datetime.now()}] [WARN] ID '{id_num}' 下的数据不是列表，将跳过或重置。")
                    DATA_STORE[id_num] = []
                    continue
                # 确保消息按接收时间倒序排列
                DATA_STORE[id_num] = sorted(
                    messages, 
                    key=lambda x: datetime.datetime.fromisoformat(x.get('receive_time', '1970-01-01T00:00:00')), 
                    reverse=True
                )
            print(f"[{datetime.datetime.now()}] [INFO] 数据从 {DATA_FILE} 加载成功，包含 {len(DATA_STORE)} 个ID。")
        except json.JSONDecodeError:
            print(f"[{datetime.datetime.now()}] [ERROR] {DATA_FILE} 不是有效的 JSON 文件，将初始化为空数据存储。")
            DATA_STORE = {}
        except ValueError as ve:
            print(f"[{datetime.datetime.now()}] [ERROR] 加载数据时发生值错误: {ve}，将初始化为空数据存储。")
            DATA_STORE = {}
        except Exception as e:
            print(f"[{datetime.datetime.now()}] [ERROR] 加载数据时发生未知错误: {e}，将初始化为空数据存储。")
            DATA_STORE = {}
    else:
        print(f"[{datetime.datetime.now()}] [INFO] 数据文件 {DATA_FILE} 不存在，将初始化为空数据存储。")
        DATA_STORE = {}

def save_data():
    """将 DATA_STORE 中的数据保存到文件"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(DATA_STORE, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[{datetime.datetime.now()}] [ERROR] 保存数据到 {DATA_FILE} 时发生错误: {e}")

# --- 电文解析辅助函数 ---
def parse_hex_content(hex_str):
    """
    解析十六进制电文内容，返回解析后的字典。
    """
    parsed_data = {"raw_hex_content": hex_str}
    
    if not isinstance(hex_str, str) or not re.fullmatch(r'^[0-9a-fA-F]*$', hex_str):
        parsed_data['parse_status_text'] = "十六进制字符串格式错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "输入不是有效的十六进制字符串。"
        return parsed_data

    try:
        byte_data = binascii.unhexlify(hex_str)
    except binascii.Error as e:
        parsed_data['parse_status_text'] = f"十六进制解码错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = f"十六进制字符串解码失败: {e}"
        return parsed_data

    offset = 0
    total_len = len(byte_data)

    # 1. 数据标识 (1 byte): A4
    if total_len < offset + 1:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析数据标识。"
        return parsed_data
    data_id = byte_data[offset]
    parsed_data['数据标识'] = f"0x{data_id:02X}"
    if data_id != 0xA4:
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 数据标识不是 0xA4。"
    offset += 1

    # 2. 定位时间 (8 bytes): hh:mm:ss
    if total_len < offset + 8:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析定位时间。"
        return parsed_data
    try:
        parsed_data['定位时间'] = byte_data[offset : offset + 8].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['定位时间'] = f"<{binascii.hexlify(byte_data[offset : offset + 8]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 定位时间解码为 ASCII 失败。"
    offset += 8

    # 3. 纬度半球 (1 byte): N/S
    if total_len < offset + 1:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析纬度半球。"
        return parsed_data
    try:
        parsed_data['纬度半球'] = byte_data[offset : offset + 1].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['纬度半球'] = f"<{binascii.hexlify(byte_data[offset : offset + 1]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 纬度半球解码为 ASCII 失败。"
    offset += 1

    # 4. 纬度 (10 bytes): ddmm.mmmmm
    if total_len < offset + 10:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析纬度。"
        return parsed_data
    try:
        parsed_data['原始纬度值'] = byte_data[offset : offset + 10].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['原始纬度值'] = f"<{binascii.hexlify(byte_data[offset : offset + 10]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 原始纬度值解码为 ASCII 失败。"
    offset += 10

    # 5. 经度半球 (1 byte): E/W
    if total_len < offset + 1:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析经度半球。"
        return parsed_data
    try:
        parsed_data['经度半球'] = byte_data[offset : offset + 1].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['经度半球'] = f"<{binascii.hexlify(byte_data[offset : offset + 1]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 经度半球解码为 ASCII 失败。"
    offset += 1

    # 6. 经度 (11 bytes): dddmm.mmmmm
    if total_len < offset + 11:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析经度。"
        return parsed_data
    try:
        parsed_data['原始经度值'] = byte_data[offset : offset + 11].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['原始经度值'] = f"<{binascii.hexlify(byte_data[offset : offset + 11]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 原始经度值解码为 ASCII 失败。"
    offset += 11

    # 7. 高程 (8 bytes): ±xxxxx.x
    if total_len < offset + 8:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析高程。"
        return parsed_data
    try:
        parsed_data['高程'] = byte_data[offset : offset + 8].decode('ascii')
    except UnicodeDecodeError:
        parsed_data['高程'] = f"<{binascii.hexlify(byte_data[offset : offset + 8]).decode()}> (解码失败)"
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 高程解码为 ASCII 失败。"
    offset += 8

    # 8. 隔离符 (1 byte): '-' (0x2D)
    if total_len < offset + 1:
        parsed_data['parse_status_text'] = "解析错误"
        parsed_data['parse_status_class'] = "error-text"
        parsed_data['parse_error_detail'] = "数据长度不足，无法解析隔离符。"
        return parsed_data
    separator = byte_data[offset]
    parsed_data['隔离符'] = f"0x{separator:02X}"
    if separator != 0x2D:
        parsed_data['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '') + " 隔离符不是 '-' (0x2D)。"
    offset += 1

    # 9. 自定义数据 (剩余字节) - 混合 GBK / ASCII 解析
    remaining_bytes = byte_data[offset:]
    custom_data_decoded_parts = []
    i = 0
    
    while i < len(remaining_bytes):
        # 尝试解析 GBK (2字节)
        if i + 1 < len(remaining_bytes):
            try:
                char_gbk = remaining_bytes[i : i + 2].decode('gbk')
                custom_data_decoded_parts.append(char_gbk)
                i += 2
                continue
            except UnicodeDecodeError:
                pass # 不是有效的 GBK 字符对，尝试作为 ASCII
        
        # 尝试解析 ASCII (1字节)
        try:
            char_ascii = remaining_bytes[i : i + 1].decode('ascii')
            custom_data_decoded_parts.append(char_ascii)
            i += 1
        except UnicodeDecodeError:
            # 既不是 GBK 也不是 ASCII，可能是数据损坏，用十六进制表示
            custom_data_decoded_parts.append(f"<{remaining_bytes[i : i + 1].hex()}>")
            i += 1

    parsed_data['自定义数据'] = ''.join(custom_data_decoded_parts)
    
    # 最终确定解析状态
    if 'parse_error_detail' in parsed_data:
        parsed_data['parse_status_text'] = parsed_data.get('parse_status_text', '解析错误')
        parsed_data['parse_status_class'] = "error-text"
    elif 'parse_warning_detail' in parsed_data:
        parsed_data['parse_status_text'] = f"解析警告: {parsed_data['parse_warning_detail'].strip()}"
        parsed_data['parse_status_class'] = "error-text"
    else:
        parsed_data['parse_status_text'] = "解析成功"
        parsed_data['parse_status_class'] = "success-text"

    return parsed_data

def convert_dmm_to_decimal(dmm_str, hemisphere):
    """
    将 ddmm.mmmmm 或 dddmm.mmmmm 格式转换为十进制。
    """
    if not isinstance(dmm_str, str) or not re.match(r'^\d+\.\d+$', dmm_str):
        return None
    try:
        parts = dmm_str.split('.')
        
        # 根据字符串长度判断是 ddmm 还是 dddmm
        if len(parts[0]) == 4: # ddmm.mmmmm
            degrees = int(parts[0][:2])
            minutes = float(parts[0][2:] + '.' + parts[1])
        elif len(parts[0]) == 5: # dddmm.mmmmm
            degrees = int(parts[0][:3])
            minutes = float(parts[0][3:] + '.' + parts[1])
        else:
            return None # 格式不匹配
        
        decimal_deg = degrees + minutes / 60
        
        if hemisphere in ['S', 'W']:
            decimal_deg = -decimal_deg
        return round(decimal_deg, 6) # 保留6位小数
    except Exception:
        return None

def format_coords(hemisphere, value_str):
    """
    格式化经纬度，并处理无效值。
    """
    if not isinstance(hemisphere, str) or not isinstance(value_str, str) or \
       not re.match(r'^[0-9.]+$', value_str):
        return f"{hemisphere if isinstance(hemisphere, str) else ''}{value_str if isinstance(value_str, str) else ''} (格式错误或缺失)"

    try:
        # 兼容 ddmm.mmmmm 和 dddmm.mmmmm 两种格式
        match = re.match(r'^(\d+)(\d{2}\.\d{5})$', value_str)
        if not match:
             # 如果原始格式不是标准的ddmm.mmmmm或dddmm.mmmmm，直接显示原始值
            return f"{hemisphere}{value_str} (格式不符)"

        degree_str = match.group(1)
        minute_str = match.group(2)
        
        hemi_map = {
            'N': '北纬', 'S': '南纬',
            'E': '东经', 'W': '西经'
        }
        hemi_full = hemi_map.get(hemisphere.upper(), hemisphere)

        return f"{hemi_full}{degree_str}°{minute_str}'"
    except Exception as e:
        return f"{hemisphere}{value_str} (解析失败: {e})"

def format_altitude(alt_str):
    """
    格式化高程，并处理无效值。
    """
    if not isinstance(alt_str, str) or not re.match(r'^[+-]?[0-9]{1,5}\.[0-9]$', alt_str):
        return f"{alt_str} (格式错误或缺失)"
    try:
        value = float(alt_str)
        formatted_value = f"{value:.1f}"
        if value >= 0 and not formatted_value.startswith('+'):
            formatted_value = '+' + formatted_value
        return f"{formatted_value}米"
    except Exception as e:
        return f"{alt_str} (解析失败: {e})"


def format_parsed_data_for_display(parsed_data, raw_post_data, receive_time):
    """
    将解析后的数据格式化为更友好的显示格式。
    注意：此函数现在直接返回一个扁平化的字典，包含所有用于显示和搜索的字段。
    同时增加十进制经纬度字段，方便地图使用。
    """
    formatted = {}

    formatted['IdNumber'] = raw_post_data.get('IdNumber', 'N/A')
    formatted['MessageId'] = raw_post_data.get('MessageId', 'N/A')
    formatted['DeliveryCount'] = raw_post_data.get('DeliveryCount', 'N/A')
    formatted['NetworkMode'] = raw_post_data.get('NetworkMode', 'N/A')
    formatted['接收时间'] = receive_time if receive_time else 'N/A'
    
    formatted['解析状态'] = {
        'text': parsed_data.get('parse_status_text', '未知状态'),
        'class': parsed_data.get('parse_status_class', '')
    }

    # 总是包含这些字段，即使在错误情况下也提供 N/A
    formatted['数据标识'] = parsed_data.get('数据标识', 'N/A')
    formatted['定位时间'] = parsed_data.get('定位时间', 'N/A')
    formatted['纬度'] = 'N/A'
    formatted['经度'] = 'N/A'
    formatted['高程'] = 'N/A'
    formatted['自定义数据'] = parsed_data.get('自定义数据', 'N/A')
    formatted['decimal_latitude'] = None # 用于地图，默认None
    formatted['decimal_longitude'] = None # 用于地图，默认None

    # 如果存在解析错误，则仅显示原始/错误信息
    if parsed_data.get('parse_status_class') == 'error-text':
        formatted['自定义数据'] = parsed_data.get('自定义数据', 'N/A') # 自定义数据可能在解析错误时仍然存在
        formatted['raw_post_data_json'] = json.dumps(raw_post_data, indent=2, ensure_ascii=False)
        return formatted


    # 解析成功或有警告时，格式化字段
    lat_hemi = parsed_data.get('纬度半球')
    lat_val = parsed_data.get('原始纬度值')
    formatted['纬度'] = format_coords(lat_hemi, lat_val)
    formatted['decimal_latitude'] = convert_dmm_to_decimal(lat_val, lat_hemi)


    lon_hemi = parsed_data.get('经度半球')
    lon_val = parsed_data.get('原始经度值')
    formatted['经度'] = format_coords(lon_hemi, lon_val)
    formatted['decimal_longitude'] = convert_dmm_to_decimal(lon_val, lon_hemi)

    formatted['高程'] = format_altitude(parsed_data.get('高程', 'N/A'))
    formatted['自定义数据'] = parsed_data.get('自定义数据', 'N/A')

    # 添加原始POST数据，方便前端搜索
    formatted['raw_post_data_json'] = json.dumps(raw_post_data, indent=2, ensure_ascii=False)

    return formatted

# --- API 路由 ---
@app.route('/api/receive', methods=['POST'])
def receive_post_data():
    req_id = request.headers.get('RequestId', str(uuid.uuid4()))
    response_payload = {"RequestId": req_id}

    if not request.is_json:
        response_payload["Code"] = "error: Content-Type must be application/json"
        print(f"[{datetime.datetime.now()}] [ERROR] Content-Type 不是 application/json。")
        return jsonify(response_payload), 400

    data = request.get_json()
    if not data:
        response_payload["Code"] = "error: Invalid JSON payload"
        print(f"[{datetime.datetime.now()}] [ERROR] 无效的 JSON payload。")
        return jsonify(response_payload), 400

    required_fields = ["IdNumber", "Content", "Time", "MessageId", "DeliveryCount", "NetworkMode"]
    for field in required_fields:
        if field not in data:
            response_payload["Code"] = f"error: Missing required field '{field}'"
            print(f"[{datetime.datetime.now()}] [ERROR] 缺少必填字段 '{field}'。Payload: {data}")
            return jsonify(response_payload), 400
        if not isinstance(data[field], str):
             response_payload["Code"] = f"error: Field '{field}' must be a string"
             print(f"[{datetime.datetime.now()}] [ERROR] 字段 '{field}' 必须是字符串。Payload: {data}")
             return jsonify(response_payload), 400

    id_number = data['IdNumber']
    content_hex = data['Content']
    receive_time = datetime.datetime.now().isoformat(timespec='seconds') # 精确到秒

    print(f"[{datetime.datetime.now()}] [INFO] API收到请求 - IdNumber: {id_number}, MessageId: {data['MessageId']}")

    parsed_content = parse_hex_content(content_hex)
    print(f"[{datetime.datetime.now()}] [INFO] 解析结果 (Id:{id_number}, MsgId:{data['MessageId']}): {parsed_content.get('parse_status_text', '未知状态')}")
    
    message_entry = {
        "raw_post_data": data,
        "parsed_content": parsed_content,
        "receive_time": receive_time
    }

    if id_number not in DATA_STORE:
        DATA_STORE[id_number] = []
    
    # 始终添加到列表开头，保持最新消息在最前面
    DATA_STORE[id_number].insert(0, message_entry)
    
    save_data()
    print(f"[{datetime.datetime.now()}] [INFO] 数据已为 IdNumber {id_number} 保存并持久化。")

    response_payload["Code"] = "ok"
    return jsonify(response_payload), 200

# 修正后的 API 接口：获取所有 ID 的最新位置数据
# 此函数现在负责处理 `id_numbers` 参数进行过滤
@app.route('/api/latest_locations', methods=['GET'])
def api_latest_locations():
    selected_ids_str = request.args.get('id_numbers') # 获取传递的ID字符串
    if selected_ids_str:
        selected_ids = [s.strip() for s in selected_ids_str.split(',') if s.strip()]
    else:
        # 如果没有指定ID，则返回 DATA_STORE 中所有ID的最新数据
        # 此时selected_ids列表为空，下面的循环会遍历所有ID
        selected_ids = list(DATA_STORE.keys()) 

    latest_data_for_response = []

    for id_num in selected_ids: # 遍历所有**需要查询**的ID
        if id_num in DATA_STORE and DATA_STORE[id_num]:
            # DATA_STORE中每个ID的消息列表已按接收时间倒序排列，第一个就是最新的
            latest_msg_entry = DATA_STORE[id_num][0] 
            
            # 使用 format_parsed_data_for_display 进行格式化和经纬度转换
            formatted_msg = format_parsed_data_for_display(
                latest_msg_entry.get('parsed_content', {}),
                latest_msg_entry.get('raw_post_data', {}),
                latest_msg_entry.get('receive_time', None)
            )

            # 只返回需要用于地图更新的关键信息
            if formatted_msg['decimal_latitude'] is not None and formatted_msg['decimal_longitude'] is not None:
                latest_data_for_response.append({
                    'IdNumber': formatted_msg['IdNumber'],
                    'decimal_latitude': formatted_msg['decimal_latitude'],
                    'decimal_longitude': formatted_msg['decimal_longitude'],
                    '接收时间': formatted_msg['接收时间'], # 前端需要这个字段来排序或显示
                    '定位时间': formatted_msg['定位时间'],
                    '自定义数据': formatted_msg['自定义数据']
                })
    
    print(f"[{datetime.datetime.now()}] [INFO] 准备返回 {len(latest_data_for_response)} 条最新位置数据 (过滤ID: {', '.join(selected_ids) if selected_ids else '所有ID'})。")
    return jsonify(latest_data_for_response)


# --- Web 路由 ---
@app.route('/')
def index():
    print(f"[{datetime.datetime.now()}] [INFO] 访问主页 '/'。")
    
    # 准备所有 ID 的所有消息，并进行格式化
    all_messages_for_frontend = {} # 格式: { "ID1": [formatted_msg1, formatted_msg2, ...], "ID2": [...] }
    sorted_id_numbers = sorted(DATA_STORE.keys()) # 保持 ID 排序

    total_unique_ids = 0
    total_all_messages_count = 0

    for id_num in sorted_id_numbers: # 确保ID有序
        messages_for_id = []
        if id_num in DATA_STORE:
            for msg_entry in DATA_STORE[id_num]:
                formatted_msg = format_parsed_data_for_display(
                    msg_entry.get('parsed_content', {}),
                    msg_entry.get('raw_post_data', {}),
                    msg_entry.get('receive_time', None)
                )
                messages_for_id.append(formatted_msg)
            
            if messages_for_id: # 只添加有消息的ID
                all_messages_for_frontend[id_num] = messages_for_id
                total_unique_ids += 1
                total_all_messages_count += len(messages_for_id)

    # 重新获取排序后的 ID 列表，现在只包含有消息的 ID
    final_sorted_id_numbers_with_messages = sorted(all_messages_for_frontend.keys())


    print(f"[{datetime.datetime.now()}] [INFO] 主页准备向前端发送所有 {total_unique_ids} 个 ID 的 {total_all_messages_count} 条消息。")
    return render_template(
        'index.html',
        # 将所有 ID 的所有消息传递给前端，前端 JS 会根据搜索条件进行过滤和渲染
        all_messages_grouped_by_id=all_messages_for_frontend, 
        sorted_id_numbers_js_arr=final_sorted_id_numbers_with_messages, # 仍然传递排序后的ID列表
        # 这两个值现在只是全局总数，前端会计算过滤后的数量
        unique_id_count_total=total_unique_ids,
        total_messages_count_total=total_all_messages_count
    )

@app.route('/history/<string:id_number_param>')
def history(id_number_param):
    print(f"[{datetime.datetime.now()}] [INFO] 访问历史页面 '/history/{id_number_param}'。")
    id_number = id_number_param

    if id_number not in DATA_STORE or not DATA_STORE[id_number]:
        print(f"[{datetime.datetime.now()}] [WARN] 未找到 ID '{id_number}' 的历史数据。")
        return render_template('not_found.html', id_number=id_number), 404

    historical_messages_raw = DATA_STORE[id_number]
    
    historical_messages_formatted = []
    for msg_entry in historical_messages_raw:
        formatted_msg = format_parsed_data_for_display(
            msg_entry.get('parsed_content', {}),
            msg_entry.get('raw_post_data', {}),
            msg_entry.get('receive_time', None)
        )
        # raw_post_data_json 已经在 format_parsed_data_for_display 中添加
        historical_messages_formatted.append(formatted_msg)

    # 从URL查询参数中获取搜索关键词
    query = request.args.get('query', '') 

    print(f"[{datetime.datetime.now()}] [INFO] ID '{id_number_param}' 历史页面已加载，包含 {len(historical_messages_formatted)} 条消息。")
    return render_template(
        'history.html',
        id_number=id_number,
        historical_messages=historical_messages_formatted, # 传递已经格式化好的消息列表
        initial_query=query # 传递搜索关键词给前端
    )

@app.route('/map')
def map_page():
    print(f"[{datetime.datetime.now()}] [INFO] 访问地图页面 '/map'。")
    
    # 与 index 路由类似，准备所有 ID 的所有消息
    all_messages_for_frontend = {} 
    sorted_id_numbers = sorted(DATA_STORE.keys())

    for id_num in sorted_id_numbers:
        messages_for_id = []
        if id_num in DATA_STORE:
            for msg_entry in DATA_STORE[id_num]:
                formatted_msg = format_parsed_data_for_display(
                    msg_entry.get('parsed_content', {}),
                    msg_entry.get('raw_post_data', {}),
                    msg_entry.get('receive_time', None)
                )
                messages_for_id.append(formatted_msg)
            
            if messages_for_id:
                all_messages_for_frontend[id_num] = messages_for_id

    final_sorted_id_numbers_with_messages = sorted(all_messages_for_frontend.keys())

    return render_template(
        'map.html',
        amap_jsapi_key=AMAP_JSAPI_KEY,
        all_messages_grouped_by_id=all_messages_for_frontend,
        sorted_id_numbers_js_arr=final_sorted_id_numbers_with_messages
    )


@app.errorhandler(404)
def page_not_found(e):
    print(f"[{datetime.datetime.now()}] [WARN] 发生 404 错误: {request.path}")
    return render_template('not_found.html'), 404

# --- 应用启动 ---
if __name__ == '__main__':
    load_data()
    print(f"[{datetime.datetime.now()}] [INFO] Flask 应用启动中...")
    app.run(host='0.0.0.0', port=5000, debug=True)

