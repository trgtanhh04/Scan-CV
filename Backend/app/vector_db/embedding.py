import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from config.config import MISTRAL_API_KEY, EMBEDDING_MODEL_NAME
from mistralai import Mistral

client = Mistral(api_key=MISTRAL_API_KEY)

def get_embedding(text: str) -> list[float]:
    res = client.embeddings.create(
        model=EMBEDDING_MODEL_NAME,
        inputs=[text]       
    )
    return res.data[0].embedding 

job_title = 'Data engineer'
technologies_used = ['Python', 'SQL', 'Spark']

query = f'job title: {job_title}, skills: {", ".join(technologies_used)}'
embedding = get_embedding(query)
print(embedding)