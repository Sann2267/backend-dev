from flask import Flask, jsonify, request, render_template
import boto3
import time
import os
from groq import Groq

app = Flask(__name__, template_folder='templates')

# Inisialisasi Klien AWS Athena
athena_client = boto3.client('athena', region_name='ap-southeast-2')

# Ambil API Key dari environment variable secara aman
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Validasi pengaman agar kontainer TIDAK CRASH jika kredensial belum siap
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    groq_client = None
    print("⚠️ PERINGATAN: GROQ_API_KEY tidak dikonfigurasi di lingkungan server!")

# Konstanta Athena
DATABASE = 'default'
TABLE = 'lks_transactions'
S3_OUTPUT = 's3://raw-transactions-lks2026/athena-results/'

def periksa_api_key():
    api_key = request.headers.get('x-api-key')
    return api_key == "LKS_LAMPUNG_2026"

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
        return "Analisis AI dilewati: Kunci API belum siap"
    try:
        prompt = f"""
        Analisis transaksi e-commerce berikut secara singkat (maksimal 10 kata) mengapa dikategorikan FRAUD/Mencurigakan:
        Item: {item}
        Nominal: Rp {amount}
        Lokasi: {location}
        Berikan jawaban langsung pada poin intinya tanpa kata pengantar.
        """
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192",
            max_tokens=30,
            temperature=0.2
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Analisis AI gagal: {str(e)}"

# 1. RUTE UTAMA: Merender Dashboard HTML
@app.route('/', methods=['GET'])
def index_dashboard():
    return render_template('dashboard.html')

# 2. RUTE API: Ambil Semua Data Transaksi
@app.route('/api/transactions', methods=['GET'])
def get_all_transactions():
    if not periksa_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key tidak valid"}), 401
        
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

# 3. RUTE API: Ambil Statistik Fraud Agregasi (Nama Fungsi Diubah ke get_fraud_stats)
@app.route('/api/fraud-stats', methods=['GET'])
def get_fraud_stats():
    if not periksa_api_key():
        return jsonify({"status": "error", "message": "Unauthorized: API Key tidak valid"}), 401

    try:
        query = f"""
            SELECT 
                is_fraud, 
                COUNT(transaction_id) as total_cases, 
                SUM(CAST(amount AS DOUBLE)) as total_amount 
            FROM {TABLE} 
            GROUP BY is_fraud;
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