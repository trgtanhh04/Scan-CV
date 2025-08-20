import pandas as pd
from pymongo import MongoClient
import ast
from tqdm import tqdm
import os
import sys
import re
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

client = MongoClient()
db = client['scan-cv']
job_collection = db['jobs']

