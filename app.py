from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
import boto3
import os
import uuid
from datetime import datetime
from boto3.dynamodb.conditions import Attr  # ✅ Required for filter expressions

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# ---------- AWS DynamoDB Configuration ----------
dynamodb = boto3.resource(
    'dynamodb',
    region_name=os.getenv('AWS_REGION'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)
USERS_TABLE = dynamodb.Table('Users')
APPOINTMENTS_TABLE = dynamodb.Table('Appointments')

# ---------- AWS SNS Configuration ----------
sns = boto3.client(
    'sns',
    region_name=os.getenv('AWS_REGION'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')

# ---------- Routes ----------

#@app.route('/')
#def home():
    #return render_template('home.html')

#@app.route('/')
#def home():
    #return redirect('/login')

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        try:
            USERS_TABLE.put_item(
                Item={'username': username, 'password': password, 'role': role},
                ConditionExpression='attribute_not_exists(username)'
            )
            flash("Registered successfully! You can now log in.")
            return redirect('/login')
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            return "User already exists!"
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        resp = USERS_TABLE.get_item(Key={'username': username})
        user = resp.get('Item')
        if user and user['password'] == password:
            session['username'] = username
            session['role'] = user['role']
            return redirect(f"/{user['role']}")
        return "Invalid login"
    return render_template('login.html')


@app.route('/patient')
def patient_dashboard():
    if session.get('role') != 'patient':
        return redirect('/login')
    resp = APPOINTMENTS_TABLE.scan(
        FilterExpression=Attr('patient_name').eq(session['username'])
    )
    appointments = resp.get('Items', [])
    appointments.sort(key=lambda x: x['created_at'], reverse=True)
    return render_template('patient_dashboard.html', username=session['username'], appointments=appointments)


@app.route('/book', methods=['GET', 'POST'])
def book_appointment():
    if session.get('role') != 'patient':
        return redirect('/login')
    if request.method == 'POST':
        appt_id = str(uuid.uuid4())
        item = {
            'id': appt_id,
            'patient_name': session['username'],
            'specialization': request.form['specialization'],
            'date': request.form['date'],
            'time': request.form['time'],
            'symptoms': request.form['symptoms'],
            'status': 'Pending',
            'response': '',
            'created_at': datetime.utcnow().isoformat()
        }
        APPOINTMENTS_TABLE.put_item(Item=item)
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=f"New appointment booked by {item['patient_name']} for {item['specialization']} on {item['date']} at {item['time']}.",
                Subject="New Appointment Notification"
            )
        except Exception as e:
            print(f"SNS Error: {e}")
        flash("Appointment booked successfully!")
        return redirect('/patient')
    return render_template('book_appointment.html')


@app.route('/doctor')
def doctor_dashboard():
    if session.get('role') != 'doctor':
        return redirect('/login')
    resp = APPOINTMENTS_TABLE.scan()
    appointments = resp.get('Items', [])
    appointments.sort(key=lambda x: x['created_at'], reverse=True)
    total = len(appointments)
    pending = sum(1 for a in appointments if a['status'] == 'Pending')
    solved = total - pending
    return render_template('doctor_dashboard.html', appointments=appointments, total=total, pending=pending, solved=solved)


@app.route('/respond/<id>', methods=['GET', 'POST'])
def respond(id):
    if session.get('role') != 'doctor':
        return redirect('/login')
    if request.method == 'POST':
        response_text = request.form['response']
        APPOINTMENTS_TABLE.update_item(
            Key={'id': id},
            UpdateExpression="SET #s = :s, response = :r",
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'Solved', ':r': response_text}
        )
        return redirect('/doctor')
    resp = APPOINTMENTS_TABLE.get_item(Key={'id': id})
    appointment = resp.get('Item')
    return render_template('respond.html', appointment=appointment)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# Run the application
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
