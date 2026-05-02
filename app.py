import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from intasend import APIService

app = Flask(__name__)

# --- 1. Database Configuration & Render Fix ---
# Render/Neon often provides 'postgres://', but SQLAlchemy requires 'postgresql://'
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. IntaSend API Setup ---
# These are pulled from your Render Environment Variables
service = APIService(
    token=os.getenv("INTASEND_SECRET_KEY"),
    publishable_key=os.getenv("INTASEND_PUBLISHABLE_KEY"),
    test=True  # Set this to False when you are ready to receive real money
)

# --- 3. Database Model ---
class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    intasend_id = db.Column(db.String(100), unique=True, nullable=False)
    client_email = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='PENDING')  # PENDING or PAID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables automatically on launch
with app.app_context():
    db.create_all()

# --- 4. Routes ---

# Home route (Used to wake up the Render Free Tier)
@app.route('/', methods=['GET'])
def home():
    return "IntaSend Bucket System: Active 🟢", 200

# Endpoint to generate a payment link for a client
@app.route('/generate-link', methods=['POST'])
def generate_link():
    data = request.json
    
    if not data or 'amount' not in data or 'email' not in data:
        return jsonify({"error": "Missing amount or email"}), 400

    try:
        # Create checkout request via IntaSend
        resp = service.collect.checkout(
            amount=data['amount'],
            currency="USD",
            email=data['email'],
            first_name=data.get('first_name', 'Client'),
            redirect_url="https://your-site-if-any.com" 
        )
        
        # Log the invoice into your Neon Database
        new_inv = Invoice(
            intasend_id=resp['id'],
            client_email=data['email'],
            amount=data['amount']
        )
        db.session.add(new_inv)
        db.session.commit()

        return jsonify({
            "success": True,
            "payment_url": resp['url'],
            "invoice_id": resp['id']
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Webhook to listen for the 'COMPLETE' signal from IntaSend
@app.route('/intasend-webhook', methods=['POST'])
def intasend_webhook():
    data = request.json
    
    # We only care about COMPLETED payments
    if data and data.get('state') == 'COMPLETE':
        invoice_id = data.get('invoice_id')
        
        # Find the record in your Neon DB
        invoice = Invoice.query.filter_by(intasend_id=invoice_id).first()
        
        if invoice:
            invoice.status = 'PAID'
            db.session.commit()
            print(f"✅ Payment Confirmed: {invoice.client_email} paid ${invoice.amount}")
            
    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    # Local port for testing, Render will use Gunicorn for production
    app.run(host='0.0.0.0', port=5000)
