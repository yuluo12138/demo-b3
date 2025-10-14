import json
import datetime
import uuid
import os # 导入os模块用于文件路径操作
from flask import Flask, request, jsonify, render_template, redirect, url_for

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
#             "receive_time": "..."
#         },
#         ...
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
                DATA_STORE = json.load(f)
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
        parsed_data['定位时间'] = byte_data[offset : offset + 8].decode('ascii', errors='replace')
        offset += 8

        # 3. 第 10-20 字节: 纬度 (11个字符，ASCII)
        lat_str = byte_data[offset : offset + 11].decode('ascii', errors='replace')
        parsed_data['纬度半球'] = lat_str[0] if lat_str else ''
        parsed_data['纬度'] = lat_str[1:] if len(lat_str) > 1 else ''
        offset += 11

        # 4. 第 21-32 字节: 经度 (12个字符，ASCII)
        lon_str = byte_data[offset : offset + 12].decode('ascii', errors='replace')
        parsed_data['经度半球'] = lon_str[0] if lon_str else ''
        parsed_data['经度'] = lon_str[1:] if len(lon_str) > 1 else ''
        offset += 12

        # 5. 第 33-40 字节: 高程 (8个字符，ASCII)
        parsed_data['高程'] = byte_data[offset : offset + 8].decode('ascii', errors='replace')
        offset += 8

        # 6. 第 41 字节: 隔离符 (1个字符，ASCII '-')
        separator_bytes = byte_data[offset : offset + 1]
        parsed_data['隔离符'] = separator_bytes.decode('ascii', errors='replace') if separator_bytes else ''
        offset += 1
        if parsed_data['隔离符'] != '-':
            parsed_data['parse_warning'] = "隔离符不为 '-'，可能影响自定义数据解析。"

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

    # 4. 解析电文内容
    parsed_content = parse_hex_content(content_hex)

    # 5. 存储数据
    if id_number not in DATA_STORE:
        DATA_STORE[id_number] = []

    DATA_STORE[id_number].append({
        "raw_post_data": data,
        "parsed_content": parsed_content,
        "receive_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # 6. 保存数据到文件 (每次更新后保存)
    save_data()

    # 7. 返回成功响应
    return jsonify({
        "RequestId": request_id,
        "Code": "ok"
    }), 200

# --- Web 路由：显示最新数据 ---
@app.route('/')
def index():
    latest_data_per_id = []
    for id_num, messages in DATA_STORE.items():
        if messages:
            latest_message = messages[-1] # 获取最新一条
            display_data = format_parsed_data(latest_message["parsed_content"])
            latest_data_per_id.append({
                "IdNumber": id_num,
                "ReceiveTime": latest_message["receive_time"],
                "ParsedData": display_data,
                "RawPostData": json.dumps(latest_message["raw_post_data"], indent=2, ensure_ascii=False)
            })
    
    # 按接收时间倒序排序，最新的显示在最前面
    latest_data_per_id.sort(key=lambda x: x["ReceiveTime"], reverse=True)
    
    return render_template('index.html', all_latest_messages=latest_data_per_id)

# --- Web 路由：显示历史数据 ---
@app.route('/history/<string:id_number>')
def history(id_number):
    if id_number not in DATA_STORE:
        return render_template('not_found.html', id_number=id_number), 404

    historical_messages_formatted = []
    # 历史数据按接收时间倒序排列，最新的在前面
    # 由于存储时是追加，所以 DATA_STORE[id_number] 是按时间顺序的，我们需要反转它
    for message in reversed(DATA_STORE[id_number]): # 反转列表以显示最新在顶部
        display_data = format_parsed_data(message["parsed_content"])
        historical_messages_formatted.append({
            "ReceiveTime": message["receive_time"],
            "ParsedData": display_data,
            "RawPostData": json.dumps(message["raw_post_data"], indent=2, ensure_ascii=False)
        })

    return render_template('history.html', id_number=id_number, historical_messages=historical_messages_formatted)


# --- 辅助函数：格式化解析后的数据用于显示 ---
def format_parsed_data(parsed_data):
    formatted = {}
    if 'parse_error' in parsed_data:
        formatted['状态'] = f"<span class='error-message'>解析错误: {parsed_data['parse_error']}</span>"
        return formatted

    formatted['状态'] = "<span class='success-message'>解析成功</span>"
    if 'parse_warning' in parsed_data:
        formatted['状态'] += f" <span class='warning-message'>警告: {parsed_data['parse_warning']}</span>"

    for key, value in parsed_data.items():
        if key in ['parse_error', 'parse_warning', '自定义数据_原始Hex']:
            continue
        
        display_value = value
        if key == '纬度半球':
            display_value = '北纬' if value == 'N' else ('南纬' if value == 'S' else value)
        elif key == '经度半球':
            display_value = '东经' if value == 'E' else ('西经' if value == 'W' else value)
        
        if key == '自定义数据' and str(value).startswith('无法解码'):
            formatted[key] = f"<span class='warning-message'>{value} (原始Hex: {parsed_data.get('自定义数据_原始Hex', 'N/A')})</span>"
        else:
            formatted[key] = display_value
    
    return formatted

# --- 应用启动时加载数据 ---
load_data()

# --- 运行应用 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

