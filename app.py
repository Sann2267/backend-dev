from flask import Flask, jsonify, render_template
import boto3
import time
import os
from groq import Groq

app = Flask(__name__, template_folder='templates')

# Ambil API Key dari environment variable secara aman
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Inisialisasi Klien AWS Athena secara aman dengan penanganan kesalahan
try:
    athena_client = boto3.client('athena', region_name='ap-southeast-2')
except Exception as e:
    print(f"PERINGATAN KREDENSIAL: Gagal inisialisasi AWS Client. Detail: {str(e)}")
    athena_client = None

DATABASE = 'default'
TABLE = 'lks_transactions'
S3_OUTPUT = 's3://raw-transactions-lks2026/athena-results/'

def run_athena_query(query_string):
    if not athena_client:
        raise Exception("AWS Athena client tidak siap karena masalah kredensial server.")
        
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
        time.sleep(0.5)  # Dipercepat dari 1 detik untuk memangkas latency

    if status != 'SUCCEEDED':
        raise Exception(f"Query Athena gagal dengan status: {status}")

    results = athena_client.get_query_results(QueryExecutionId=query_execution_id)
    return parse_athena_results(results)

def parse_athena_results(results):
    columns = [col['Label'].lower() for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']]
    parsed_data = []
    
    for row in results['ResultSet']['Rows'][1:]:
        row_data = {}
        for idx, value in enumerate(row['Data']):
            row_data[columns[idx]] = value.get('VarCharValue', None)
        parsed_data.append(row_data)
    return parsed_data

def dapatkan_analisis_groq(item, amount, location):
    if not groq_client:
        return "Analisis AI dilewati: GROQ Key belum dikonfigurasi"
    try:
        prompt = (
            f"Item: {item}, Nominal: Rp {amount}, Lokasi: {location}. "
            "Berikan HANYA alasan singkat (maks 10 kata) mengapa transaksi ini mencurigakan. "
            "Jangan gunakan markdown, jangan tambahkan pengantar apapun. Langsung tulis alasannya."
        )
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            max_tokens=30,
            temperature=0.2
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Analisis AI gagal: {str(e)}"

# 1. RUTE UTAMA: Dashboard HTML
@app.route('/', methods=['GET'])
def index_dashboard():
    return render_template('dashboard.html')

# 2. RUTE API: Ambil Semua Data Transaksi
@app.route('/api/transactions', methods=['GET'])
def get_all_transactions():
    try:
        query = f"SELECT * FROM {TABLE} LIMIT 50;"
        data = run_athena_query(query)
        
        for tx in data:
            is_fraud = tx.get('is_fraud') == 'true' or tx.get('is_fraud') == True
            if is_fraud and (not tx.get('fraud_reason') or tx.get('fraud_reason') == '-'):
                tx['fraud_reason'] = dapatkan_analisis_groq(
                    tx.get('item', '-'), 
                    tx.get('amount', '0'), 
                    tx.get('location', '-')
                )
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 3. RUTE API: Ambil Statistik Fraud Agregasi
@app.route('/api/fraud-stats', methods=['GET'])
def get_fraud_stats():
    try:
        query = f"""
            SELECT is_fraud, COUNT(transaction_id) as total_cases, SUM(CAST(amount AS DOUBLE)) as total_amount 
            FROM {TABLE} GROUP BY is_fraud;
        """
        data = run_athena_query(query)
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 4. RUTE API: Health Check
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
