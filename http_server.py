from flask import Flask, request, jsonify, render_template_string
import uuid

app = Flask(__name__)

# 全局数据存储：字典，key为IdNumber，value为数据字典
data_store = {}

# POST路由：接收JSON数据
@app.route('/api/receive', methods=['POST'])
def receive_data():
    # 检查Content-Type
    if request.content_type != 'application/json':
        return jsonify({"RequestId": str(uuid.uuid4()), "Code": "error_invalid_content_type"}), 400
    
    try:
        data = request.get_json()
        
        # 提取系统级参数
        request_id = data.get('RequestId', str(uuid.uuid4()))  # 如果没有，提供默认UUID
        
        # 提取应用级参数，并检查必填
        required_fields = ['IdNumber', 'Content', 'Time', 'MessageId', 'DeliveryCount', 'NetworkMode']
        for field in required_fields:
            if field not in data:
                return jsonify({"RequestId": request_id, "Code": "error_missing_fields"}), 400
        
        id_number = data['IdNumber']
        
        # 存储数据（根据IdNumber区分，如果重复覆盖）
        data_store[id_number] = {
            'IdNumber': id_number,
            'MessageId': data['MessageId'],
            'Content': data['Content'],
            'Time': data['Time'],
            'DeliveryCount': data['DeliveryCount'],
            'NetworkMode': data['NetworkMode']
        }
        
        # 返回成功响应
        return jsonify({"RequestId": request_id, "Code": "ok"}), 200
    
    except Exception as e:
        # 异常处理，如JSON解析失败
        return jsonify({"RequestId": str(uuid.uuid4()), "Code": f"error_internal: {str(e)}"}), 500

# GET路由：展示网页表格
@app.route('/', methods=['GET'])
def show_table():
    # HTML模板字符串
    html_template = '''
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
        <h1>接收到的数据表格</h1>
        <table>
            <tr>
                <th>IdNumber</th>
                <th>MessageId</th>
                <th>Content</th>
                <th>Time</th>
                <th>DeliveryCount</th>
                <th>NetworkMode</th>
            </tr>
            {% if data_items %}
                {% for item in data_items %}
                <tr>
                    <td>{{ item['IdNumber'] }}</td>
                    <td>{{ item['MessageId'] }}</td>
                    <td>{{ item['Content'] }}</td>
                    <td>{{ item['Time'] }}</td>
                    <td>{{ item['DeliveryCount'] }}</td>
                    <td>{{ item['NetworkMode'] }}</td>
                </tr>
                {% endfor %}
            {% else %}
                <tr><td colspan="6">暂无数据</td></tr>
            {% endif %}
        </table>
    </body>
    </html>
    '''
    
    # 将data_store转换为列表，便于模板渲染
    data_items = list(data_store.values())
    
    return render_template_string(html_template, data_items=data_items)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

