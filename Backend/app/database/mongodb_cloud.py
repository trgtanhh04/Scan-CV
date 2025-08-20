import pandas as pd
from pymongo import MongoClient
import ast
from tqdm import tqdm
import os
import sys
import re
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from vector_db.embedding import get_embedding
from config.config import MONGO_URL


client = MongoClient(MONGO_URL)
db = client['scan-cv']
job_collection = db['jobs']

BASE_DIR = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
job_path = os.path.join(BASE_DIR, '..', 'raw', 'jobs/preprocessed_data.csv')
jobs_df = pd.read_csv(job_path)

# pre-processing
list_columns = [
    "industry", "company_nationality", "position_level",
    "employment_type", "contract_type", "technologies_used"
]

def clean_list_string(val):
    if pd.isna(val):
        return []
    if isinstance(val, list):
        return val
    try:
        val = str(val)
        val = re.sub(r"[\[\]]", "", val) 
        parts = [x.strip(" '\"") for x in val.split(",") if x.strip(" '\"")]
        return parts
    except Exception:
        return []

for col in list_columns:
    if col in jobs_df.columns:
        jobs_df[col] = jobs_df[col].apply(clean_list_string)

def fix_address(val):
    if isinstance(val, list) and len(val) == 1:
        return val[0] 
    elif isinstance(val, str):
        try:
            parsed = ast.literal_eval(val)
            if isinstance(parsed, list) and len(parsed) == 1:
                return parsed[0]
        except:
            pass
    return val

if "company_size" in jobs_df.columns:
    jobs_df["company_size"] = pd.to_numeric(jobs_df["company_size"], errors="coerce")

def text_emb(job_title, technologies_used):
    query = f'job title: {job_title}, skills: {", ".join(technologies_used)}'
    return get_embedding(query)

docs = []
for _, row in tqdm(jobs_df.iterrows(), total=len(jobs_df), desc="Embedding & build docs"):
    # job_title = row.get('job_title', '')
    # techs = row.get('technologies_used', '')

    doc = row.to_dict()
    # emd = text_emb(job_title, techs)
    # doc['embedding'] = emd
    docs.append(doc)
    time.sleep(1.1)

# Insert documents into MongoDB
if docs:
    job_collection.insert_many(docs)
    print(f"Inserted {len(docs)} documents into MongoDB.")
else:
    print("No documents to insert into MongoDB.")