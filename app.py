import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from intasend import APIService

app = Flask(__name__)

# --- Fix for SQLAlchemy/Render Postgres URL ---
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- IntaSend Setup ---
service = APIService(
    token=os.getenv("INTASEND_SECRET_KEY"),
    publishable_key=os.getenv("INTASEND_PUBLISHABLE_KEY"),
    test=True # Set to False for Live money
)

# --- Simple Database Table ---
class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    intasend_id = db.Column(db.String(100), unique=True)
    client_email = db.Column(db.String(120))
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='PENDING') # PENDING or PAID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return "IntaSend Bucket Active 🟢", 200

# Route to generate the link Paul sends to the client
@app.route('/generate-link', methods=['POST'])
def generate():
    data = request.json
    try:
        resp = service.collect.checkout(
            amount=data['amount'], 
            currency="USD", 
            email=data['email']
        )
        # Log the request in our Neon DB
        new_inv = Invoice(
            intasend_id=resp['id'], 
            client_email=data['email'], 
            amount=data['amount']
        )
        db.session.add(new_inv)
        db.session.commit()
        
        return jsonify({"payment_url": resp['url']}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Webhook that listens for the client's payment
@app.route('/intasend-webhook', methods=['POST'])
def webhook():
    data = request.json
    # Only update our DB if the payment is complete
    if data.get('state') == 'COMPLETE':
        inv = Invoice.query.filter_by(intasend_id=data.get('invoice_id')).first()
        if inv:
            inv.status = 'PAID'
            db.session.commit()
            print(f"✅ Payment for {inv.client_email} recorded.")
            
    return jsonify({"status": "received"}), 200
