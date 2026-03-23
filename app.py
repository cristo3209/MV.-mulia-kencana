import os
import uuid
import io
from datetime import datetime
from flask import Flask, render_template, request, send_file, abort
from cryptography.fernet import Fernet
import qrcode
from fpdf import FPDF
import pymysql
import pymysql.cursors

app = Flask(__name__)

# ==================== ENKRIPSI ====================
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"Generated new encryption key: {ENCRYPTION_KEY}")
    print("Please set ENCRYPTION_KEY environment variable for production!")
cipher = Fernet(ENCRYPTION_KEY.encode())

# ==================== DATABASE (MySQL) ====================
# Ganti dengan detail database MySQL Anda dari PythonAnywhere
# Biasanya: username.mysql.pythonanywhere-services.com
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'YOUR_USERNAME.mysql.pythonanywhere-services.com'),
    'user': os.environ.get('MYSQL_USER', 'YOUR_USERNAME'),
    'password': os.environ.get('MYSQL_PASSWORD', 'YOUR_PASSWORD'),
    'database': os.environ.get('MYSQL_DB', 'YOUR_USERNAME$default'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    return pymysql.connect(**DB_CONFIG)

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS bookings (
                    id VARCHAR(8) PRIMARY KEY,
                    full_name VARCHAR(100) NOT NULL,
                    encrypted_passport TEXT NOT NULL,
                    departure_date DATE NOT NULL,
                    departure_time VARCHAR(5) NOT NULL,
                    return_date DATE,
                    return_time VARCHAR(5),
                    adult_count INT NOT NULL,
                    child_count INT NOT NULL,
                    total_price INT NOT NULL,
                    trip_type VARCHAR(10) NOT NULL,
                    booking_date DATETIME NOT NULL
                )
            ''')
            conn.commit()
    print("Database initialized")

def save_booking(data):
    encrypted_passport = cipher.encrypt(data['passportNumber'].encode()).decode()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO bookings (
                    id, full_name, encrypted_passport, departure_date, departure_time,
                    return_date, return_time, adult_count, child_count, total_price,
                    trip_type, booking_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                data['booking_id'], data['fullName'], encrypted_passport,
                data['departureDate'], data['departureTime'],
                data.get('returnDate'), data.get('returnTime'),
                data['adultCount'], data['childCount'], data['totalPrice'],
                data['tripType'], datetime.now()
            ))
            conn.commit()

# ==================== PDF GENERATOR ====================
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'MV. MULIA KENCANA - E-TICKET', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Halaman {self.page_no()}', 0, 0, 'C')

def generate_pdf(booking_data):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', '', 12)

    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'TIKET KAPAL', 0, 1, 'L')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 8, f'Kode Booking: {booking_data["booking_id"]}', 0, 1)
    pdf.cell(0, 8, f'Nama: {booking_data["fullName"]}', 0, 1)
    pdf.cell(0, 8, f'Nomor Passport: {booking_data["passportNumber"]}', 0, 1)

    pdf.cell(0, 8, f'Keberangkatan: {booking_data["departureDate"]} - {booking_data["departureTime"]} WIB (Indonesia → Malaysia)', 0, 1)
    if booking_data.get('returnDate'):
        pdf.cell(0, 8, f'Kepulangan: {booking_data["returnDate"]} - {booking_data["returnTime"]} WIB (Malaysia → Indonesia)', 0, 1)

    total_people = booking_data["adultCount"] + booking_data["childCount"]
    pdf.cell(0, 8, f'Jumlah Penumpang: {total_people} orang', 0, 1)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, f'Total Harga: Rp {booking_data["totalPrice"]:,}', 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 5, '* Tiket ini tidak dapat dipindahtangankan.', 0, 1)

    # QR Code
    base_url = os.environ.get('BASE_URL', 'https://YOUR_USERNAME.pythonanywhere.com')
    verification_url = f"{base_url}/verify/{booking_data['booking_id']}"
    qr_img = qrcode.make(verification_url)
    img_buffer = io.BytesIO()
    qr_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    pdf.image(img_buffer, x=pdf.get_x() + 80, y=pdf.get_y() + 10, w=50)
    pdf.ln(60)

    pdf.cell(0, 10, 'Terima kasih telah memilih MV. Mulia Kencana', 0, 1, 'C')
    pdf.cell(0, 8, 'Scan QR untuk verifikasi tiket', 0, 1, 'C')

    pdf_output = io.BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)
    return pdf_output

# ==================== ROUTES ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/book', methods=['POST'])
def book():
    try:
        full_name = request.form.get('fullName', '').strip()
        passport_number = request.form.get('passportNumber', '').strip()
        departure_date = request.form.get('departureDate', '').strip()
        departure_time = request.form.get('departureTime', '').strip()
        return_date = request.form.get('returnDate', '').strip() or None
        return_time = request.form.get('returnTime', '').strip() or None
        adult_count = int(request.form.get('adultCount', 0))
        child_count = int(request.form.get('childCount', 0))

        if not all([full_name, passport_number, departure_date, departure_time, adult_count]):
            abort(400, description="Data tidak lengkap")
        if return_date and not return_time:
            abort(400, description="Jika tanggal pulang diisi, waktu pulang harus diisi")

        trip_type = 'roundtrip' if return_date and return_time else 'oneway'
        total_people = adult_count + child_count
        if trip_type == 'roundtrip':
            price_per_person = 800000
        else:
            price_per_person = 600000
        total_price = total_people * price_per_person
        booking_id = str(uuid.uuid4())[:8].upper()

        booking_data = {
            'booking_id': booking_id,
            'fullName': full_name,
            'passportNumber': passport_number,
            'departureDate': departure_date,
            'departureTime': departure_time,
            'returnDate': return_date,
            'returnTime': return_time,
            'adultCount': adult_count,
            'childCount': child_count,
            'totalPrice': total_price,
            'tripType': trip_type
        }

        save_booking(booking_data)
        pdf_buffer = generate_pdf(booking_data)

        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f'tiket_{booking_id}.pdf',
            mimetype='application/pdf'
        )
    except Exception as e:
        return str(e), 500

@app.route('/verify/<booking_id>')
def verify_ticket(booking_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bookings WHERE id = %s', (booking_id,))
            row = cur.fetchone()
    if not row:
        abort(404, description="Tiket tidak ditemukan")
    passport_number = cipher.decrypt(row['encrypted_passport'].encode()).decode()
    return render_template('verify.html', booking=row, passport=passport_number)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
