import pandas as pd
from pymongo import MongoClient
import ast
from tqdm import tqdm
import os
import sys
import re
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config.config import MONGO_URL, OPENAI_API_KEY


client = MongoClient(MONGO_URL)
db = client['scan-cv']
job_collection = db['jobs']

BASE_DIR = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
job_path = os.path.join(BASE_DIR, '..', 'raw', 'jobs/preprocessed_data.csv')
jobs_df = pd.read_csv(job_path)
