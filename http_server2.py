# 导入模块
from flask import Flask, request, jsonify, render_template_string
import uuid  # 生成 RequestId

app = Flask(__name__)

# 全局数据存储：字典，键为 IdNumber，值包含原始和解析字段（半球已转换为中文）
data_store = {}  # 示例：{'2019070111201': {'MessageId': '1', 'RequestTime': '2021-12-16 10:30:33', ..., 'LatHem': '北纬', ...}}

# 半球转换字典
hemisphere_map = {
    'N': '北纬',
    'S': '南纬',
    'E': '东经',
    'W': '西经'
}

# POST 路由：接收数据到 /api/receive
@app.route('/api/receive', methods=['POST'])
def receive_data():
    # 检查系统级 Content-Type
    content_type = request.headers.get('Content-Type')
    if content_type != 'application/json':
        return jsonify({"RequestId": str(uuid.uuid4()), "Code": "error: Invalid Content-Type"}), 400
    
    # 解析 JSON
    try:
        data = request.json
    except:
        return jsonify({"RequestId": str(uuid.uuid4()), "Code": "error: Invalid JSON"}), 400
    
    # 获取 RequestId（可选，否则生成）
    request_id = data.get('RequestId', str(uuid.uuid4()))
    
    # 检查应用级必须字段
    required_fields = ['IdNumber', 'Content', 'Time', 'MessageId', 'DeliveryCount', 'NetworkMode']
    for field in required_fields:
        if field not in data:
            return jsonify({"RequestId": request_id, "Code": f"error: Missing {field}"}), 400
    
    # 验证 Content 长度
    if len(data['Content']) > 3500:
        return jsonify({"RequestId": request_id, "Code": "error: Content too long"}), 400
    
    # 解析 Content（十六进制字符串）
    content_hex = data['Content']
    try:
        if not content_hex.startswith('A4'):
            raise ValueError("Content must start with 'A4'")
        
        # 转为字节
        bytes_data = bytes.fromhex(content_hex)
        
        # 跳过起始 A4 字节（1字节），用 GBK 解码剩余部分
        str_data = bytes_data[1:].decode('gbk')
        
        # 按固定位置切片解析（固定部分至少40字符）
        if len(str_data) < 40:
            raise ValueError("Content too short for parsing")
        
        loc_time = str_data[0:8]      # 定位时间 hh:mm:ss
        lat_hem = str_data[8:9]       # 纬度半球 N/S
        lat = str_data[9:19]          # 纬度 ddmm.mmmmm
        lon_hem = str_data[19:20]     # 经度半球 E/W
        lon = str_data[20:31]         # 经度 dddmm.mmmmm
        alt = str_data[31:39]         # 高程 ±99999.9
        sep = str_data[39:40]         # 隔离符 -
        custom = str_data[40:]        # 自定义数据
        
        if sep != '-':
            raise ValueError("Invalid separator")
        
        # 转换半球为中文
        lat_hem_cn = hemisphere_map.get(lat_hem.upper(), lat_hem)  # 如果无效，用原值
        lon_hem_cn = hemisphere_map.get(lon_hem.upper(), lon_hem)
        
        # 存储数据：原始 + 解析（半球已转换）
        id_number = data['IdNumber']
        data_store[id_number] = {
            'MessageId': data['MessageId'],
            'RequestTime': data['Time'],  # 请求中的 Time（UTC）
            'DeliveryCount': data['DeliveryCount'],
            'NetworkMode': data['NetworkMode'],
            'LocTime': loc_time,          # 解析：定位时间
            'LatHem': lat_hem_cn,         # 纬度半球（中文）
            'Lat': lat,                   # 纬度
            'LonHem': lon_hem_cn,         # 经度半球（中文）
            'Lon': lon,                   # 经度
            'Alt': alt,                   # 高程
            'Custom': custom              # 自定义数据
        }
        
        # 成功返回
        return jsonify({"RequestId": request_id, "Code": "ok"})
    
    except Exception as e:
        # 解析失败返回错误
        return jsonify({"RequestId": request_id, "Code": f"error: Content parsing failed - {str(e)}"}), 400

# GET 路由：显示网页表格到根路径 /
@app.route('/', methods=['GET'])
def show_data():
    # HTML 模板：表格展示所有字段，根据 IdNumber 区分行
    html = """
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <title>数据展示</title>
        <style>
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid black; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <h1>接收到的数据表格（根据 IdNumber 区分）</h1>
        <table>
            <tr>
                <th>IdNumber</th>
                <th>MessageId</th>
                <th>RequestTime</th>
                <th>DeliveryCount</th>
                <th>NetworkMode</th>
                <th>LocTime (定位时间)</th>
                <th>LatHem (纬度半球)</th>
                <th>Lat (纬度)</th>
                <th>LonHem (经度半球)</th>
                <th>Lon (经度)</th>
                <th>Alt (高程)</th>
                <th>Custom (自定义数据)</th>
            </tr>
            {% if data_store %}
                {% for id_number, item in data_store.items() %}
                <tr>
                    <td>{{ id_number }}</td>
                    <td>{{ item['MessageId'] }}</td>
                    <td>{{ item['RequestTime'] }}</td>
                    <td>{{ item['DeliveryCount'] }}</td>
                    <td>{{ item['NetworkMode'] }}</td>
                    <td>{{ item['LocTime'] }}</td>
                    <td>{{ item['LatHem'] }}</td>
                    <td>{{ item['Lat'] }}</td>
                    <td>{{ item['LonHem'] }}</td>
                    <td>{{ item['Lon'] }}</td>
                    <td>{{ item['Alt'] }}</td>
                    <td>{{ item['Custom'] }}</td>
                </tr>
                {% endfor %}
            {% else %}
                <tr><td colspan="12">无数据</td></tr>
            {% endif %}
        </table>
    </body>
    </html>
    """
    return render_template_string(html, data_store=data_store)

# 运行服务器
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

