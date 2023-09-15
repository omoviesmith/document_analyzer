from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import NoCredentialsError
import os
from PyPDF2 import PdfReader
from textblob import TextBlob
import docx2txt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.


app = Flask(__name__) 

# Configure database
app.config['S3_BUCKET'] = 'forsentiments'
app.config['S3_URL'] = 'https://s3.amazonaws.com/forsentiments'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///documents.db'
app.config['UPLOAD_FOLDER'] = 'C:\\Users\\Smith\\Postman\\files'


db = SQLAlchemy(app)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=True) 

class SentimentDictionary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    Word = db.Column(db.String(120), nullable=True)
    Seq_num = db.Column(db.Integer, default=0)
    Word_Count = db.Column(db.Integer, default=0)
    Word_Proportion = db.Column(db.Float, default=0)
    Average_Proportion = db.Column(db.Float, default=0)
    Std_Dev = db.Column(db.Float, default=0)
    Doc_Count = db.Column(db.Integer, default=0)
    Negative = db.Column(db.Integer)
    Positive = db.Column(db.Integer)
    Uncertainty = db.Column(db.Integer, default=0)
    Litigious = db.Column(db.Integer, default=0)
    Strong_Modal = db.Column(db.Integer, default=0)
    Weak_Modal = db.Column(db.Integer, default=0)
    Constraining = db.Column(db.Integer, default=0)
    Syllables = db.Column(db.Integer, default=0)
    Source = db.Column(db.String(120), default="12of12inf")

@app.route('/api/documents/<int:document_id>', methods=['GET'])
def get_document(document_id):
    document = Document.query.get_or_404(document_id)
    
    response = {
        'id': document.id,
        'name': document.name,
        'content': document.content
    }

    filename = document.name
    file_url = f"{app.config['S3_URL']}/{filename}"
    return jsonify({'id': document.id, 'name': document.name, 'content': document.content, 'file_url': file_url})
    
    #return jsonify(response)

@app.route('/api/documents', methods=['POST'])
def upload_document():

    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request.'}), 400

    file = request.files['file']

    if file.filename.endswith('.pdf'):
        pdf = PdfReader(file)
        content = ''
        #for page in range(pdf.getNumPages()):
        for page in pdf.pages:
            content += page.extract_text()

    elif file.filename.endswith('.docx'):
        content = docx2txt.process(file)

    else:
        return jsonify({'error': 'Invalid file format.'}), 400

    # filename = secure_filename(file.filename)
    # file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    s3 = boto3.client('s3')
    bucket_name = app.config['S3_BUCKET']
    filename = secure_filename(file.filename)
    s3.upload_fileobj(file, bucket_name, filename)
    file_url = f"{app.config['S3_URL']}/{filename}"


    new_document = Document(name=filename, content=content)
    db.session.add(new_document)
    db.session.commit()

    return jsonify({'id': new_document.id, 'name': new_document.name}), 201


@app.route('/api/documents/<int:document_id>/find_replace', methods=['PUT'])
def find_replace(document_id):
    
    document = Document.query.get_or_404(document_id)
    
    old_word = request.json.get('old_word')
    new_word = request.json.get('new_word')
    replace_all = request.json.get('replace_all', False)

    if not old_word or not new_word:
        return jsonify({'error': 'Both old_word and new_word are required.'}), 400

    if not isinstance(old_word, str) or not isinstance(new_word, str):
        return jsonify({'error': 'Both old_word and new_word have to be of string type.'}), 400

    if replace_all:
        document.content = document.content.replace(old_word, new_word)
    else:
        document.content = document.content.replace(old_word, new_word, 1)
    
    db.session.commit()
    
    return jsonify({'message': 'Document content updated successfully.', 'content': document.content})

@app.route('/api/upload_dictionary', methods=['POST'])
def upload_dictionary():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']

    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files allowed'}), 400

    filename = secure_filename(file.filename)
    s3 = boto3.client('s3')
    bucket_name = app.config['S3_BUCKET']
    s3.upload_fileobj(file, bucket_name, filename)
    file_url = f"{app.config['S3_URL']}/{filename}"

    # Load data into pandas dataframe
    dataframe = pd.read_csv(file_url)
    dataframe = dataframe.fillna(0) #fill nan with 0
    inspector = inspect(db.engine)

    if 'sentiment_dictionary' in inspector.get_table_names():
        SentimentDictionary.__table__.drop(db.engine)

    # create the table
    SentimentDictionary.__table__.create(db.engine)

    # insert dataframe into the table
    dataframe.to_sql('sentiment_dictionary', con=db.engine, if_exists='replace', index=False)

    return jsonify({'message': 'Sentiment dictionary uploaded successfully'}), 201

@app.route('/api/documents/<int:document_id>/analyze', methods=['GET'])
def analyze_document(document_id):
    document = Document.query.get_or_404(document_id)

    if document.content is None:
        return jsonify({'error': 'Document content is empty.'}), 400

    sentiment_dictionary = SentimentDictionary.query.all()

    positive_words = []
    negative_words = []

    for word in sentiment_dictionary:
        if word.Positive != 0:
            positive_words.append(word.Word.lower())
        if word.Negative != 0:
            negative_words.append(word.Word.lower())

    blob = TextBlob(document.content.lower())
    positive_hits = [word for word in blob.words if word in positive_words]
    negative_hits = [word for word in blob.words if word in negative_words]

    total_words = len(blob.words)
    net_positivity_score = (len(positive_hits) - len(negative_hits)) / total_words

    response = {
        'positive_words': positive_hits,
        'negative_words': negative_hits,
        'net_positivity_score': net_positivity_score
    }

    return jsonify(response)
@app.route('/files/<path:filename>', methods=['GET'])
def download_file(filename):
    s3 = boto3.client('s3')
    bucket_name = app.config['S3_BUCKET']
    try:
        s3.download_file(bucket_name, filename, f'/tmp/{filename}')
        return send_from_directory('/tmp', filename, as_attachment=True)
    except NoCredentialsError:
        return jsonify({'error': 'AWS credentials not found.'}), 500
        
with app.app_context():
    # Perform database operations here, such as db.create_all()
    db.create_all()

if __name__ == '__main__':
    with app.app_context():
        # Perform database operations here, such as db.create_all()
        db.create_all()

    app.run(debug=True)
