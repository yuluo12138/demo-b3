import json
import datetime
import uuid
import os
import re
import math
from flask import Flask, request, jsonify, render_template, abort, url_for
from urllib.parse import quote_plus
from collections import defaultdict
import binascii

app = Flask(__name__)

# --- 配置 ---
DATA_FILE = 'data_store.json'
# 全局数据存储，结构: {"IdNumber": [{"raw_post_data": {}, "parsed_content": {}, "receive_time": ""}, ...]}
# 每个 IdNumber 下的消息列表是按 receive_time 倒序存储的，最新的在最前面
DATA_STORE = {}

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
            
            # 确保每个 IdNumber 下的消息列表都是按 receive_time 倒序排列
            for id_num, messages in DATA_STORE.items():
                if not isinstance(messages, list):
                    print(f"[{datetime.datetime.now()}] [WARN] ID '{id_num}' 下的数据不是列表，将跳过或重置。")
                    DATA_STORE[id_num] = []
                    continue
                DATA_STORE[id_num] = sorted(
                    messages, key=lambda x: datetime.datetime.fromisoformat(x.get('receive_time', '1970-01-01T00:00:00')), reverse=True
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
        # print(f"[{datetime.datetime.now()}] [DEBUG] 数据已保存到 {DATA_FILE}。") # 频繁打印，可根据需要取消注释
    except Exception as e:
        print(f"[{datetime.datetime.now()}] [ERROR] 保存数据到 {DATA_FILE} 时发生错误: {e}")

# --- 电文解析辅助函数 ---
def parse_hex_content(hex_str):
    """
    解析十六进制电文内容，返回解析后的字典。
    结构: A4 + 定位时间(8) + 纬度半球(1) + 纬度(10) + 经度半球(1) + 经度(11) + 高程(8) + 隔离符(1) + 自定义数据(N)
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
        parsed_data['parse_status_text'] = parsed_data.get('parse_status_text', '解析错误') # 使用前面设置的错误文本
        parsed_data['parse_status_class'] = "error-text"
    elif 'parse_warning_detail' in parsed_data:
        # 根据要求，警告也归为错误显示
        parsed_data['parse_status_text'] = f"解析警告: {parsed_data['parse_warning_detail'].strip()}"
        parsed_data['parse_status_class'] = "error-text"
    else:
        parsed_data['parse_status_text'] = "解析成功"
        parsed_data['parse_status_class'] = "success-text"


    return parsed_data

def format_coords(hemisphere, value_str):
    """
    格式化经纬度，并处理无效值。
    例如: N4005.76783 -> 北纬40°05.76783'
    """
    if not isinstance(hemisphere, str) or not isinstance(value_str, str) or \
       not re.match(r'^[0-9.]+$', value_str):
        return f"{hemisphere if isinstance(hemisphere, str) else ''}{value_str if isinstance(value_str, str) else ''} (格式错误或缺失)"

    try:
        # 匹配 度分.分小数 的模式
        match = re.match(r'^(\d+)(\d{2}\.\d{5})$', value_str)
        if not match:
            return f"{hemisphere}{value_str} (格式不符ddmm.mmmmm或dddmm.mmmmm)"

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
    例如: +00099.5 -> +99.5米, -00010.2 -> -10.2米
    """
    if not isinstance(alt_str, str) or not re.match(r'^[+-]?[0-9]{1,5}\.[0-9]$', alt_str):
        return f"{alt_str} (格式错误或缺失)"
    try:
        value = float(alt_str)
        # Python float格式化会移除不必要的0，但我们希望保留小数点后一位
        # 使用 f-string 格式化，并手动处理正号，负号会自动带上
        formatted_value = f"{value:.1f}"
        if value >= 0 and not formatted_value.startswith('+'): # 确保正数有+号
            formatted_value = '+' + formatted_value
        return f"{formatted_value}米"
    except Exception as e:
        return f"{alt_str} (解析失败: {e})"


def format_parsed_data_for_display(parsed_data, raw_post_data, receive_time):
    """
    将解析后的数据格式化为更友好的显示格式。
    现在返回的 '解析状态' 会是 {text: "...", class: "..."} 的字典。
    """
    formatted = {}

    # 从 raw_post_data 中提取关键信息
    formatted['IdNumber'] = raw_post_data.get('IdNumber', 'N/A')
    formatted['MessageId'] = raw_post_data.get('MessageId', 'N/A')
    formatted['DeliveryCount'] = raw_post_data.get('DeliveryCount', 'N/A')
    formatted['NetworkMode'] = raw_post_data.get('NetworkMode', 'N/A')
    formatted['接收时间'] = receive_time if receive_time else 'N/A'
    
    # 解析状态现在是一个字典，包含文本和类名
    formatted['解析状态'] = {
        'text': parsed_data.get('parse_status_text', '未知状态'),
        'class': parsed_data.get('parse_status_class', '')
    }

    # 如果是严重解析错误，就不再尝试格式化其他字段
    if parsed_data.get('parse_status_class') == 'error-text':
        # 在错误情况下，定位时间等字段可能缺失，统一显示为N/A
        formatted['数据标识'] = parsed_data.get('数据标识', 'N/A')
        formatted['定位时间'] = parsed_data.get('定位时间', 'N/A')
        formatted['纬度'] = 'N/A'
        formatted['经度'] = 'N/A'
        formatted['高程'] = 'N/A'
        formatted['自定义数据'] = parsed_data.get('自定义数据', 'N/A') # 自定义数据可能部分解析成功
        # 传递错误详情以便在前端展示
        formatted['parse_error_detail'] = parsed_data.get('parse_error_detail', '')
        formatted['parse_warning_detail'] = parsed_data.get('parse_warning_detail', '')
        return formatted


    formatted['数据标识'] = parsed_data.get('数据标识', 'N/A')
    formatted['定位时间'] = parsed_data.get('定位时间', 'N/A')
    
    # 格式化纬度
    lat_hemi = parsed_data.get('纬度半球')
    lat_val = parsed_data.get('原始纬度值')
    formatted['纬度'] = format_coords(lat_hemi, lat_val)

    # 格式化经度
    lon_hemi = parsed_data.get('经度半球')
    lon_val = parsed_data.get('原始经度值')
    formatted['经度'] = format_coords(lon_hemi, lon_val)
    
    formatted['高程'] = format_altitude(parsed_data.get('高程', 'N/A'))
    formatted['自定义数据'] = parsed_data.get('自定义数据', 'N/A')

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
        if not isinstance(data[field], str): # 确保这些字段是字符串
             response_payload["Code"] = f"error: Field '{field}' must be a string"
             print(f"[{datetime.datetime.now()}] [ERROR] 字段 '{field}' 必须是字符串。Payload: {data}")
             return jsonify(response_payload), 400

    id_number = data['IdNumber']
    content_hex = data['Content']
    receive_time = datetime.datetime.now().isoformat() # 服务器接收时间

    print(f"[{datetime.datetime.now()}] [INFO] API收到请求 - IdNumber: {id_number}, MessageId: {data['MessageId']}")

    parsed_content = parse_hex_content(content_hex)
    # 这里打印使用 pure text，避免日志中出现HTML
    print(f"[{datetime.datetime.now()}] [INFO] 解析结果 (Id:{id_number}, MsgId:{data['MessageId']}): {parsed_content.get('parse_status_text', '未知状态')}")
    
    # 存储原始 POST 数据，解析结果和接收时间
    message_entry = {
        "raw_post_data": data,
        "parsed_content": parsed_content,
        "receive_time": receive_time
    }

    if id_number not in DATA_STORE:
        DATA_STORE[id_number] = []
    
    # 插入到列表开头，确保最新消息总在最前面
    DATA_STORE[id_number].insert(0, message_entry)
    
    # 持久化数据
    save_data()
    print(f"[{datetime.datetime.now()}] [INFO] 数据已为 IdNumber {id_number} 保存并持久化。")

    response_payload["Code"] = "ok"
    return jsonify(response_payload), 200

# --- Web 路由 ---
@app.route('/')
def index():
    print(f"[{datetime.datetime.now()}] [INFO] 访问主页 '/'。")
    # 准备前端展示所需的数据
    all_messages_grouped_for_frontend = {}
    for id_num, messages in DATA_STORE.items():
        if not messages: # 如果某个ID下没有消息，跳过
            continue
        
        # 主页只显示最新的1条消息，但包含所有解析字段，方便搜索
        latest_message_entry = messages[0] 
        
        # 将原始解析数据完全格式化，包含所有字段
        formatted_data = format_parsed_data_for_display(
            latest_message_entry.get('parsed_content', {}),
            latest_message_entry.get('raw_post_data', {}),
            latest_message_entry.get('receive_time', None) # 传递 None 允许 format_parsed_data_for_display 处理 'N/A'
        )
        all_messages_grouped_for_frontend[id_num] = {
            "latest_message": formatted_data,
            "total_count": len(messages)
        }

    unique_id_count = len(DATA_STORE)
    total_messages_count = sum(len(msgs) for msgs in DATA_STORE.values())
    
    # 确保 IdNumber 在前端按字母顺序显示
    sorted_id_numbers = sorted(DATA_STORE.keys())

    print(f"[{datetime.datetime.now()}] [INFO] 主页准备向前端发送 {len(all_messages_grouped_for_frontend)} 个分组数据。")
    return render_template(
        'index.html',
        # 直接使用 tojson 过滤器将 Python 字典/列表安全地转换为 JavaScript 对象字面量
        all_messages_grouped_js_obj=all_messages_grouped_for_frontend,
        sorted_id_numbers_js_arr=sorted_id_numbers,
        unique_id_count=unique_id_count,
        total_messages_count=total_messages_count
    )

@app.route('/history/<string:id_number_param>')
def history(id_number_param):
    print(f"[{datetime.datetime.now()}] [INFO] 访问历史页面 '/history/{id_number_param}'。")
    id_number = id_number_param # URL path 中获取的 IdNumber

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
        # 将原始 POST 数据也传递给模板，以便在页面上显示
        formatted_msg['raw_post_data_json'] = json.dumps(msg_entry.get('raw_post_data', {}), indent=2, ensure_ascii=False)
        historical_messages_formatted.append(formatted_msg)

    print(f"[{datetime.datetime.now()}] [INFO] ID '{id_number_param}' 历史页面已加载，包含 {len(historical_messages_formatted)} 条消息。")
    return render_template(
        'history.html',
        id_number=id_number,
        historical_messages=historical_messages_formatted
    )

@app.errorhandler(404)
def page_not_found(e):
    print(f"[{datetime.datetime.now()}] [WARN] 发生 404 错误: {request.path}")
    return render_template('not_found.html'), 404


# --- 应用启动 ---
if __name__ == '__main__':
    load_data() # 在应用启动前加载数据
    print(f"[{datetime.datetime.now()}] [INFO] Flask 应用启动中...")
    # debug=True 会在代码改动时自动重启，并且提供更详细的错误信息
    app.run(host='0.0.0.0', port=5000, debug=True) 

