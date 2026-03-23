import os
import sqlite3
import uuid
import io
from datetime import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for
from cryptography.fernet import Fernet
import qrcode
from fpdf import FPDF

app = Flask(__name__)

# ==================== ENKRIPSI ====================
# Generate atau load kunci enkripsi
# Simpan kunci di environment variable untuk production
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    # Generate kunci baru jika belum ada (untuk development)
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"Generated new encryption key: {ENCRYPTION_KEY}")
    print("Please set ENCRYPTION_KEY environment variable for production!")
cipher = Fernet(ENCRYPTION_KEY.encode())

# ==================== DATABASE ====================
DB_NAME = 'database.db'

def init_db():
    """Buat tabel bookings jika belum ada"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                encrypted_passport TEXT NOT NULL,
                departure_date TEXT NOT NULL,
                departure_time TEXT NOT NULL,
                return_date TEXT,
                return_time TEXT,
                adult_count INTEGER NOT NULL,
                child_count INTEGER NOT NULL,
                total_price INTEGER NOT NULL,
                trip_type TEXT NOT NULL,
                booking_date TEXT NOT NULL
            )
        ''')

def save_booking(data):
    """Simpan data booking ke database dengan passport terenkripsi"""
    encrypted_passport = cipher.encrypt(data['passportNumber'].encode()).decode()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            INSERT INTO bookings (
                id, full_name, encrypted_passport, departure_date, departure_time,
                return_date, return_time, adult_count, child_count, total_price,
                trip_type, booking_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['booking_id'],
            data['fullName'],
            encrypted_passport,
            data['departureDate'],
            data['departureTime'],
            data.get('returnDate'),
            data.get('returnTime'),
            data['adultCount'],
            data['childCount'],
            data['totalPrice'],
            data['tripType'],
            datetime.now().isoformat()
        ))

# ==================== PDF GENERATOR ====================
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'KM MULIA KENCANA - E-TICKET', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Halaman {self.page_no()}', 0, 0, 'C')

def generate_pdf(booking_data, qr_image_bytes):
    """Buat PDF tiket dan return sebagai BytesIO"""
    pdf = PDF()
    pdf.add_page()
    pdf.set_font('Arial', '', 12)

    # Detail pemesanan
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, 'TIKET KAPAL', 0, 1, 'L')
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 8, f'Kode Booking: {booking_data["booking_id"]}', 0, 1)
    pdf.cell(0, 8, f'Nama: {booking_data["fullName"]}', 0, 1)
    pdf.cell(0, 8, f'Nomor Passport: {booking_data["passportNumber"]}', 0, 1)

    # Rute
    pdf.cell(0, 8, f'Keberangkatan: {booking_data["departureDate"]} - {booking_data["departureTime"]} WIB (Indonesia → Malaysia)', 0, 1)
    if booking_data.get('returnDate'):
        pdf.cell(0, 8, f'Kepulangan: {booking_data["returnDate"]} - {booking_data["returnTime"]} WIB (Malaysia → Indonesia)', 0, 1)

    # Penumpang & harga
    pdf.cell(0, 8, f'Penumpang: {booking_data["adultCount"]} Dewasa, {booking_data["childCount"]} Anak', 0, 1)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, f'Total Harga: Rp {booking_data["totalPrice"]:,}', 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 5, '* Tiket ini tidak dapat dipindahtangankan.', 0, 1)

    # Sisipkan QR Code
    # Simpan QR code ke file sementara di memory
    qr_img = qrcode.make(booking_data["booking_id"])  # QR berisi kode booking
    img_buffer = io.BytesIO()
    qr_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    # Tempatkan gambar di PDF
    pdf.image(img_buffer, x=pdf.get_x() + 80, y=pdf.get_y() + 10, w=50)
    pdf.ln(60)

    pdf.cell(0, 10, 'Terima kasih telah memilih Mulia Kencana', 0, 1, 'C')

    # Simpan PDF ke BytesIO
    pdf_output = io.BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)
    return pdf_output

# ==================== ROUTE FLASK ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/book', methods=['POST'])
def book():
    # Ambil data dari form
    full_name = request.form.get('fullName')
    passport_number = request.form.get('passportNumber')
    departure_date = request.form.get('departureDate')
    departure_time = request.form.get('departureTime')
    return_date = request.form.get('returnDate')
    return_time = request.form.get('returnTime')
    adult_count = int(request.form.get('adultCount', 0))
    child_count = int(request.form.get('childCount', 0))

    # Validasi sederhana
    if not all([full_name, passport_number, departure_date, departure_time, adult_count]):
        return "Data tidak lengkap", 400

    # Tentukan tipe perjalanan
    trip_type = 'roundtrip' if return_date and return_time else 'oneway'

    # Hitung harga (contoh: harga sesuai permintaan sebelumnya)
    # Harga dewasa one way = 600.000, return = 800.000; anak one way = 400.000, return = 500.000
    if trip_type == 'roundtrip':
        price_adult = 800000
        price_child = 500000
    else:
        price_adult = 600000
        price_child = 400000

    total_price = (adult_count * price_adult) + (child_count * price_child)

    # Buat ID booking unik
    booking_id = str(uuid.uuid4())[:8].upper()

    # Data untuk disimpan (passport akan dienkripsi di fungsi save)
    booking_data = {
        'booking_id': booking_id,
        'fullName': full_name,
        'passportNumber': passport_number,
        'departureDate': departure_date,
        'departureTime': departure_time,
        'returnDate': return_date if trip_type == 'roundtrip' else None,
        'returnTime': return_time if trip_type == 'roundtrip' else None,
        'adultCount': adult_count,
        'childCount': child_count,
        'totalPrice': total_price,
        'tripType': trip_type
    }

    # Simpan ke database (passport otomatis dienkripsi)
    save_booking(booking_data)

    # Generate PDF tiket
    pdf_buffer = generate_pdf(booking_data, None)  # QR code dihasilkan di dalam generate_pdf

    # Kembalikan PDF sebagai file download
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f'tiket_{booking_id}.pdf',
        mimetype='application/pdf'
    )

# ==================== INIT DATABASE ====================
if __name__ == '__main__':
    init_db()
    app.run(debug=True)