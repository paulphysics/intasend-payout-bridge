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
    test=True # Set to False when you go live
)

# --- Database Model ---
class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    intasend_id = db.Column(db.String(100), unique=True, nullable=False)
    client_email = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='PENDING')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Auto-create tables
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return "Payment Bridge Active 🟢", 200

@app.route('/generate-link', methods=['POST'])
def generate():
    data = request.json
    try:
        resp = service.collect.checkout(amount=data['amount'], currency="USD", email=data['email'])
        new_inv = Invoice(intasend_id=resp['id'], client_email=data['email'], amount=data['amount'])
        db.session.add(new_inv)
        db.session.commit()
        return jsonify({"url": resp['url']}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/intasend-webhook', methods=['POST'])
def webhook():
    data = request.json
    inv = Invoice.query.filter_by(intasend_id=data.get('invoice_id')).first()
    if inv and data.get('state') == 'COMPLETE' and inv.status == 'PENDING':
        inv.status = 'COMPLETED'
        db.session.commit()
        try:
            payout = service.transfer.mpesa_b2c(currency="KES", transactions=[{
                "name": "Payout",
                "account": os.getenv("MPESA_PHONE_NUMBER"),
                "amount": data.get('value'),
                "narrative": "Payout"
            }])
            service.transfer.approve(payout)
            inv.status = 'DISBURSED'
            db.session.commit()
        except Exception as e:
            print(f"Payout failed: {e}")
    return jsonify({"status": "received"}), 200
