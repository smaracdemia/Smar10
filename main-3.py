
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import hashlib
import json
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import secrets
import string

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# Required payment details
REQUIRED_NAME = "YABETS AKALU GEBREMICHAEL"
REQUIRED_ACCOUNT = "1000650258367"
MINIMUM_AMOUNT = 10
PROCESSED_HASHES_FILE = 'processed_screenshots.json'
VALID_EXAMS = ['aastu1', 'aastu2', 'aastu3', 'aau1', 'aau2', 'aau3']

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_image_hash(image_path):
    """Generate hash of image for duplicate detection"""
    with open(image_path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def load_processed_hashes():
    """Load previously processed screenshot hashes"""
    if os.path.exists(PROCESSED_HASHES_FILE):
        with open(PROCESSED_HASHES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_processed_hash(image_hash, user_info):
    """Save processed screenshot hash"""
    processed_hashes = load_processed_hashes()
    processed_hashes[image_hash] = {
        'timestamp': datetime.now().isoformat(),
        'user_info': user_info
    }
    with open(PROCESSED_HASHES_FILE, 'w') as f:
        json.dump(processed_hashes, f)

def generate_secure_token():
    """Generate a secure one-time token"""
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

def preprocess_image(image_path):
    """Preprocess image for better OCR results"""
    # Read image
    img = cv2.imread(image_path)
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Apply denoising
    denoised = cv2.fastNlMeansDenoising(gray)
    
    # Apply threshold to get image with only black and white
    _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    return thresh

def extract_text_from_image(image_path):
    """Extract text from image using OCR"""
    try:
        # Preprocess image
        processed_img = preprocess_image(image_path)
        
        # Use pytesseract to extract text
        text = pytesseract.image_to_string(processed_img, config='--psm 6')
        return text.strip()
    except Exception as e:
        print(f"Error extracting text: {e}")
        return ""

def verify_payment_details(text):
    """Verify payment details in extracted text"""
    text_upper = text.upper()
    
    # Check for required name or account
    name_found = REQUIRED_NAME.upper() in text_upper
    account_found = REQUIRED_ACCOUNT in text
    
    if not (name_found or account_found):
        return False, "Required name or account number not found"
    
    # Extract amount using regex
    amount_patterns = [
        r'ETB\s*(\d+(?:\.\d{2})?)',
        r'AMOUNT\s*:?\s*(\d+(?:\.\d{2})?)',
        r'(\d+(?:\.\d{2})?)\s*ETB',
        r'(\d+(?:,\d{3})*(?:\.\d{2})?)'
    ]
    
    amount_found = False
    extracted_amount = 0
    
    for pattern in amount_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            try:
                # Take the largest amount found
                amounts = [float(match.replace(',', '')) for match in matches]
                extracted_amount = max(amounts)
                if extracted_amount >= MINIMUM_AMOUNT:
                    amount_found = True
                    break
            except ValueError:
                continue
    
    if not amount_found:
        return False, f"Valid amount (>= {MINIMUM_AMOUNT} ETB) not found"
    
    # Check for today's date
    today = datetime.now()
    date_patterns = [
        today.strftime('%Y-%m-%d'),
        today.strftime('%d/%m/%Y'),
        today.strftime('%d-%m-%Y'),
        today.strftime('%Y/%m/%d'),
        today.strftime('%d %B %Y'),
        today.strftime('%B %d, %Y')
    ]
    
    date_found = any(date_pattern in text for date_pattern in date_patterns)
    
    if not date_found:
        return False, "Today's date not found in screenshot"
    
    return True, f"Payment verified successfully. Amount: {extracted_amount} ETB"

@app.route('/')
def index():
    exam = request.args.get('exam', '')
    if exam and exam not in VALID_EXAMS:
        flash('❌ Invalid exam type specified')
        exam = ''
    return render_template('index.html', exam=exam)

@app.route('/upload', methods=['POST'])
def upload_file():
    # Get exam parameter from form or URL
    exam = request.form.get('exam') or request.args.get('exam', '')
    
    if 'file' not in request.files:
        flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date.')
        return redirect(url_for('index', exam=exam))
    
    file = request.files['file']
    if file.filename == '':
        flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date.')
        return redirect(url_for('index', exam=exam))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Check for duplicate screenshots
        image_hash = get_image_hash(file_path)
        processed_hashes = load_processed_hashes()
        
        if image_hash in processed_hashes:
            os.remove(file_path)  # Remove duplicate file
            flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date. For support: @smarexam')
            return redirect(url_for('index', exam=exam))
        
        # Extract text from image
        extracted_text = extract_text_from_image(file_path)
        
        if not extracted_text:
            os.remove(file_path)
            flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date. For support: @smarexam')
            return redirect(url_for('index', exam=exam))
        
        # Verify payment details
        is_valid, message = verify_payment_details(extracted_text)
        
        if is_valid:
            # Save hash to prevent reuse
            save_processed_hash(image_hash, {
                'filename': filename,
                'verification_message': message,
                'exam': exam
            })
            
            # Generate secure token and redirect to exam
            if exam and exam in VALID_EXAMS:
                token = generate_secure_token()
                exam_url = f"https://smaracademia.netlify.app/exam/{exam}?token={token}"
                return redirect(exam_url)
            else:
                flash(f'✅ PAYMENT VERIFIED SUCCESSFULLY! {message}')
        else:
            flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date. For support: @smarexam')
        
        # Clean up uploaded file
        os.remove(file_path)
        
        return redirect(url_for('index', exam=exam))
    
    flash('❌ Invalid screenshot. Must include name, 10 birr, and today\'s date. For support: @smarexam')
    return redirect(url_for('index', exam=exam))

@app.route('/requirements')
def requirements():
    return render_template('requirements.html')

