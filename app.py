from flask import Flask, jsonify, request, render_template
import boto3
import time

app = Flask(__name__)

athena_client = boto3.client('athena', region_name='ap-southeast-2')

SECRET_API_KEY = "LKS_LAMPUNG_2026"

# Konstanta Athena
DATABASE = 'default'
TABLE = 'lks_transactions'
S3_OUTPUT = 's3://raw-transactions-lks2026/athena-results/'

def run_athena_query(query_string):
    response = athena_client.start_query_execution(
        QueryString=query_string,
        QueryExecutionContext={'Database': DATABASE},
        ResultConfiguration={'OutputLocation': S3_OUTPUT}
    )
    query_execution_id = response['QueryExecutionId']

    while True:
        status_response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
        status = status_response['QueryExecution']['Status']['State']
        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            break
        time.sleep(1)

    if status != 'SUCCEEDED':
        raise Exception(f"Query gagal dengan status: {status}")

    results = athena_client.get_query_results(QueryExecutionId=query_execution_id)
    return parse_athena_results(results)

def parse_athena_results(results):
    columns = [col['Label'] for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']]
    parsed_data = []
    
    for row in results['ResultSet']['Rows'][1:]:
        row_data = {}
        for idx, value in enumerate(row['Data']):
            row_data[columns[idx]] = value.get('VarCharValue', None)
        parsed_data.append(row_data)
        
    return parsed_data

def check_api_key():
    api_key = request.headers.get('x-api-key')
    if not api_key or api_key != SECRET_API_KEY:
        return False
    return True

@app.route('/', methods=['GET'])
def index_dashboard():
    return render_template('dashboard.html')

@app.route('/health', methods=['GET'])
def health_check():
    if not check_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key salah atau tidak ditemukan"}), 401
        
    return jsonify({"status": "healthy"}), 200

@app.route('/api/transactions', methods=['GET'])
def get_all_transactions():
    if not check_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key salah atau tidak ditemukan"}), 401

    try:
        query = f"SELECT * FROM {TABLE} LIMIT 50;"
        data = run_athena_query(query)
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/fraud-stats', methods=['GET'])
def get_fraud_stats():
    if not periksa_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key salah atau tidak ditemukan"}), 401

    try:
        # Memberikan alias huruf kecil yang konsisten agar mudah dibaca oleh JavaScript
        query = f"""
            SELECT 
                is_fraud, 
                COUNT(transaction_id) as total_cases, 
                SUM(amount) as total_amount 
            FROM {TABLE} 
            GROUP BY is_fraud;
        """
        data = run_athena_query(query)
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    if not check_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key salah atau tidak ditemukan"}), 401

    try:
        body_data = request.get_json()
        if not body_data:
            return jsonify({"status": "error", "message": "Bad Request: JSON body tidak boleh kosong"}), 400

        transaction_id = body_data.get('transaction_id', f"trx_{int(time.time())}")
        amount = body_data.get('amount', 0)
        item = body_data.get('item', 'Unknown Item')

        return jsonify({
            "status": "success",
            "message": "Simulasi data transaksi diterima dengan aman",
            "received_data": {
                "transaction_id": transaction_id,
                "amount": amount,
                "item": item
            }
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
