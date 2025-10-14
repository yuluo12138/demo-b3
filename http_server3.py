import json
import datetime
import uuid
import os
from flask import Flask, request, jsonify, render_template, redirect, url_for
from urllib.parse import quote_plus # 用于URL编码，在前端链接中使用

app = Flask(__name__)

# --- 数据持久化配置 ---
DATA_FILE = 'data_store.json' # 存储数据的文件名，将在应用根目录生成

# 全局数据存储
# 结构:
# {
#     "IdNumber1": [
#         {
#             "raw_post_data": {...},
#             "parsed_content": { ... },
#             "receive_time": "YYYY-MM-DD HH:MM:SS"
#         },
#         ... (多条消息按接收时间倒序存储，最新的在前面)
#     ],
#     "IdNumber2": [...]
# }
DATA_STORE = {}

# --- 数据持久化辅助函数 ---
def load_data():
    """从文件中加载数据到DATA_STORE"""
    global DATA_STORE
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # 确保每组内的消息按时间倒序排列，最新的在前面
                # (尽管append会保持顺序，但如果文件被手动编辑，这里可以修复)
                for id_num, messages in loaded_data.items():
                    loaded_data[id_num] = sorted(messages, key=lambda x: x["receive_time"], reverse=True)
                DATA_STORE = loaded_data
            print(f"数据已从 {DATA_FILE} 加载。")
        except json.JSONDecodeError as e:
            print(f"警告: {DATA_FILE} 文件内容损坏，无法解析JSON: {e}。将初始化为空数据存储。")
            DATA_STORE = {}
        except Exception as e:
            print(f"加载数据时发生未知错误: {e}。将初始化为空数据存储。")
            DATA_STORE = {}
    else:
        print(f"数据文件 {DATA_FILE} 不存在，将初始化为空数据存储。")
        DATA_STORE = {}

def save_data():
    """将DATA_STORE中的数据保存到文件"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            # ensure_ascii=False 确保中文字符以原始形式写入，而非转义序列
            json.dump(DATA_STORE, f, indent=2, ensure_ascii=False)
        print(f"数据已保存到 {DATA_FILE}。")
    except Exception as e:
        print(f"保存数据到 {DATA_FILE} 时发生错误: {e}")

# --- 辅助函数：解析电文十六进制字符串 ---
def parse_hex_content(hex_str):
    """
    解析十六进制电文内容。
    Args:
        hex_str (str): 十六进制字符串，如 "A430373A34363A3230..."
    Returns:
        dict: 包含解析结果的字典，如果解析失败则包含 'parse_error' 字段。
    """
    parsed_data = {}
    try:
        # 将十六进制字符串转换为字节序列
        byte_data = bytes.fromhex(hex_str)

        # 检查电文起始A4
        if not byte_data or byte_data[0] != 0xA4:
            parsed_data['parse_error'] = "电文起始字节不是 A4"
            return parsed_data

        offset = 0

        # 1. 第1字节: 数据标识 (0xA4)
        offset += 1

        # 2. 第 2-9 字节: 定位时间 (8个字符，ASCII)
        # 确保有足够的字节
        if len(byte_data) < offset + 8: raise IndexError("定位时间字节不足")
        parsed_data['定位时间'] = byte_data[offset : offset + 8].decode('ascii', errors='replace')
        offset += 8

        # 3. 第 10-20 字节: 纬度 (11个字符，ASCII)
        # N/S ddmm.mmmmm
        if len(byte_data) < offset + 11: raise IndexError("纬度字节不足")
        lat_full_str = byte_data[offset : offset + 11].decode('ascii', errors='replace')
        if len(lat_full_str) == 11 and (lat_full_str[0] == 'N' or lat_full_str[0] == 'S'):
            parsed_data['纬度半球'] = lat_full_str[0]
            parsed_data['纬度原始值'] = lat_full_str[1:] # 存储原始值用于后续格式化
        else:
            parsed_data['纬度半球'] = lat_full_str[0] if lat_full_str else ''
            parsed_data['纬度原始值'] = lat_full_str[1:] if len(lat_full_str) > 1 else lat_full_str
            if parsed_data['纬度半球'] not in ['N', 'S']:
                parsed_data['parse_warning'] = parsed_data.get('parse_warning', '') + "纬度半球格式不正确或长度不足; "
        offset += 11

        # 4. 第 21-32 字节: 经度 (12个字符，ASCII)
        # E/W dddmm.mmmmm
        if len(byte_data) < offset + 12: raise IndexError("经度字节不足")
        lon_full_str = byte_data[offset : offset + 12].decode('ascii', errors='replace')
        if len(lon_full_str) == 12 and (lon_full_str[0] == 'E' or lon_full_str[0] == 'W'):
            parsed_data['经度半球'] = lon_full_str[0]
            parsed_data['经度原始值'] = lon_full_str[1:] # 存储原始值用于后续格式化
        else:
            parsed_data['经度半球'] = lon_full_str[0] if lon_full_str else ''
            parsed_data['经度原始值'] = lon_full_str[1:] if len(lon_full_str) > 1 else lon_full_str
            if parsed_data['经度半球'] not in ['E', 'W']:
                parsed_data['parse_warning'] = parsed_data.get('parse_warning', '') + "经度半球格式不正确或长度不足; "
        offset += 12

        # 5. 第 33-40 字节: 高程 (8个字符，ASCII)
        if len(byte_data) < offset + 8: raise IndexError("高程字节不足")
        parsed_data['高程'] = byte_data[offset : offset + 8].decode('ascii', errors='replace')
        offset += 8

        # 6. 第 41 字节: 隔离符 (1个字符，ASCII '-')
        if len(byte_data) < offset + 1: raise IndexError("隔离符字节不足")
        separator_bytes = byte_data[offset : offset + 1]
        parsed_data['隔离符'] = separator_bytes.decode('ascii', errors='replace') if separator_bytes else ''
        offset += 1
        if parsed_data['隔离符'] != '-':
            parsed_data['parse_warning'] = parsed_data.get('parse_warning', '') + "隔离符不为 '-'，可能影响自定义数据解析; "

        # 7. 自定义数据 (N个字符)
        custom_data_bytes = byte_data[offset:]
        parsed_data['自定义数据_原始Hex'] = custom_data_bytes.hex().upper()
        
        if custom_data_bytes:
            try:
                # 优先尝试GBK解码，errors='replace'处理无法解码的字符
                parsed_data['自定义数据'] = custom_data_bytes.decode('gbk', errors='replace')
            except Exception:
                # 尝试UTF-8解码
                try:
                    parsed_data['自定义数据'] = custom_data_bytes.decode('utf-8', errors='replace')
                except Exception:
                    # 如果都失败，则显示原始字节的表示
                    parsed_data['自定义数据'] = f"无法解码({custom_data_bytes.hex()})"
        else:
            parsed_data['自定义数据'] = "无"

    except ValueError as e:
        parsed_data['parse_error'] = f"十六进制解析错误: {e}"
    except IndexError as e:
        parsed_data['parse_error'] = f"字节数据不足，解析错误: {e}"
    except Exception as e:
        parsed_data['parse_error'] = f"未知解析错误: {e}"

    return parsed_data

# --- 辅助函数：格式化解析后的数据用于显示 (现在仅负责数据格式化，不包含HTML标签，方便JS处理) ---
def format_parsed_data_for_display(parsed_data, raw_post_data, id_number, receive_time):
    """
    格式化解析后的数据和原始数据，用于前端展示。
    返回的字典值不再是HTML标签，而是纯文本，以便前端进行高亮处理。
    """
    formatted = {}
    
    # 将接收时间也作为可搜索和展示的字段
    formatted['最新接收时间'] = receive_time

    if 'parse_error' in parsed_data:
        formatted['状态'] = f"解析错误: {parsed_data['parse_error']}"
        return formatted

    formatted['状态'] = "解析成功"
    if 'parse_warning' in parsed_data:
        formatted['状态'] += f" 警告: {parsed_data['parse_warning']}"

    # 纬度
    lat_hemisphere = parsed_data.get('纬度半球', '')
    lat_raw = parsed_data.get('纬度原始值', '')
    if len(lat_raw) >= 2 and '.' in lat_raw:
        try:
            degrees = lat_raw[0:2]
            minutes = lat_raw[2:]
            formatted['纬度'] = f"{'北纬' if lat_hemisphere == 'N' else ('南纬' if lat_hemisphere == 'S' else lat_hemisphere)}{degrees}°{minutes}'"
        except Exception:
            formatted['纬度'] = f"{lat_hemisphere}{lat_raw} (格式错误)"
    else:
        formatted['纬度'] = f"{('北纬' if lat_hemisphere == 'N' else ('南纬' if lat_hemisphere == 'S' else lat_hemisphere))}{lat_raw}"

    # 经度
    lon_hemisphere = parsed_data.get('经度半球', '')
    lon_raw = parsed_data.get('经度原始值', '')
    if len(lon_raw) >= 3 and '.' in lon_raw:
        try:
            degrees = lon_raw[0:3]
            minutes = lon_raw[3:]
            formatted['经度'] = f"{'东经' if lon_hemisphere == 'E' else ('西经' if lon_hemisphere == 'W' else lon_hemisphere)}{degrees}°{minutes}'"
        except Exception:
            formatted['经度'] = f"{lon_hemisphere}{lon_raw} (格式错误)"
    else:
        formatted['经度'] = f"{('东经' if lon_hemisphere == 'E' else ('西经' if lon_hemisphere == 'W' else lon_hemisphere))}{lon_raw}"

    # 其他字段直接取值
    formatted['定位时间'] = parsed_data.get('定位时间', 'N/A')
    formatted['高程'] = parsed_data.get('高程', 'N/A')
    
    custom_data = parsed_data.get('自定义数据', '无')
    if str(custom_data).startswith('无法解码'):
        # 自定义数据显示出错，但仍然要显示原始Hex
        formatted['自定义数据'] = f"{custom_data} (原始Hex: {parsed_data.get('自定义数据_原始Hex', 'N/A')})"
    else:
        formatted['自定义数据'] = custom_data

    # 将原始POST数据中的一些关键字段也添加到格式化数据中，方便搜索
    formatted['IdNumber'] = id_number # 使用传入的IdNumber
    formatted['MessageId'] = raw_post_data.get('MessageId', 'N/A')
    formatted['NetworkMode'] = raw_post_data.get('NetworkMode', 'N/A')
    
    return formatted


# --- API 路由：接收POST数据 ---
@app.route('/api/receive', methods=['POST'])
def receive_post_data():
    request_id = request.headers.get('RequestId', str(uuid.uuid4()))
    content_type = request.headers.get('Content-Type')

    # 1. 验证 Content-Type
    if not content_type or not content_type.lower().startswith('application/json'):
        return jsonify({
            "RequestId": request_id,
            "Code": "error",
            "Message": "Content-Type must be application/json"
        }), 400

    # 2. 获取 JSON 数据
    try:
        data = request.get_json()
        if not data:
            raise ValueError("Invalid or empty JSON data")
    except Exception as e:
        return jsonify({
            "RequestId": request_id,
            "Code": "error",
            "Message": f"Failed to parse JSON: {e}. Please ensure all JSON delimiters are half-width characters."
        }), 400

    # 3. 验证应用级输入参数
    required_fields = ['IdNumber', 'Content', 'Time', 'MessageId', 'DeliveryCount', 'NetworkMode']
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({
            "RequestId": request_id,
            "Code": "error",
            "Message": f"Missing required fields: {', '.join(missing_fields)}"
        }), 400

    id_number = data.get('IdNumber')
    content_hex = data.get('Content')
    current_receive_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 4. 解析电文内容
    parsed_content = parse_hex_content(content_hex)
    
    # 5. 存储数据
    if id_number not in DATA_STORE:
        DATA_STORE[id_number] = []

    # 将新消息添加到列表的开头，确保最新的消息在前面
    DATA_STORE[id_number].insert(0, {
        "raw_post_data": data,
        "parsed_content": parsed_content,
        "receive_time": current_receive_time # 使用实际的服务器接收时间
    })
    
    # 6. 保存数据到文件 (每次更新后保存)
    save_data()

    # 7. 返回成功响应
    return jsonify({
        "RequestId": request_id,
        "Code": "ok"
    }), 200


# --- Web 路由：显示数据 (现在将所有数据传给前端，由前端处理搜索和渲染) ---
@app.route('/')
def index():
    # 获取默认的今天日期字符串用于前端
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 准备所有数据，按IdNumber分组，每组内按时间倒序
    all_messages_grouped_for_frontend = {}
    total_messages_count = 0 # 统计所有消息的总条数
    unique_id_count = 0 # 统计唯一IdNumber的数量

    sorted_id_numbers = sorted(DATA_STORE.keys()) # 按IdNumber字母顺序排序

    for id_num in sorted_id_numbers:
        messages_for_id = []
        if id_num in DATA_STORE:
            unique_id_count += 1
            # DATA_STORE[id_num] 已经是按时间倒序的
            for message in DATA_STORE[id_num]:
                total_messages_count += 1
                formatted_data = format_parsed_data_for_display(
                    message["parsed_content"], 
                    message["raw_post_data"], 
                    id_num, 
                    message["receive_time"]
                )
                messages_for_id.append({
                    "IdNumber": id_num,
                    "ReceiveTime": message["receive_time"], # 原始接收时间
                    "ParsedData": formatted_data,
                    "RawPostData": json.dumps(message["raw_post_data"], indent=2, ensure_ascii=False)
                })
        all_messages_grouped_for_frontend[id_num] = messages_for_id
    
    return render_template('index.html', 
                           all_messages_grouped_json=json.dumps(all_messages_grouped_for_frontend, ensure_ascii=False),
                           today_date=today,
                           unique_id_count=unique_id_count, # 传递给前端
                           total_messages_count=total_messages_count)

# --- Web 路由：显示历史数据 ---
@app.route('/history/<string:id_number>')
def history(id_number):
    if id_number not in DATA_STORE:
        return render_template('not_found.html', id_number=id_number), 404

    historical_messages_formatted = []
    # 历史数据按接收时间倒序排列，最新的在前面（存储时已保证）
    for message in DATA_STORE[id_number]: 
        # 调用新的格式化函数，包含 receive_time
        display_data = format_parsed_data_for_display(
            message["parsed_content"], 
            message["raw_post_data"], 
            id_number, 
            message["receive_time"] # 传递接收时间
        )
        historical_messages_formatted.append({
            "ReceiveTime": message["receive_time"],
            "ParsedData": display_data,
            "RawPostData": json.dumps(message["raw_post_data"], indent=2, ensure_ascii=False)
        })

    return render_template('history.html', id_number=id_number, historical_messages=historical_messages_formatted)


# --- 应用启动时加载数据 ---
load_data()

# --- 运行应用 ---
if __name__ == '__main__':
    # Flask默认在开发模式下启动，生产环境请使用Gunicorn等WSGI服务器
    app.run(host='0.0.0.0', port=5000, debug=True)

