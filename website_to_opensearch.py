import logging
import os

import boto3

from tqdm import trange
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_aws import BedrockEmbeddings
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
from dotenv import load_dotenv

from utils.crawler import Crawler

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)

if __name__ == '__main__':
    load_dotenv()

    region = os.getenv("AWS_REGION")
    service = "aoss"

    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, service, session_token=credentials.token)

    aoss_host = os.getenv("OPENSEARCH_HOST")

    opensearch_client = OpenSearch(
        hosts=[{'host': aoss_host, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=20,
    )
    index_name = os.getenv("OPENSEARCH_INDEX")

    crawler = Crawler(starturl=os.getenv('CRAWLER_URL'), max_sites=int(os.getenv('MAX_PAGES')))
    crawler.run()

    exit(0)

    embedding_model = BedrockEmbeddings(model_id=os.getenv('TEXT_EMBEDDING_MODEL'))
    batch_size = 1
    text_embeddings = []
    documents = []
    metadatas = []
    for url, docs in crawler.get_site_docs().items():
        for doc in docs:
            documents.append(doc)

    for i in trange(0, len(documents), batch_size, desc="Create embeddings"):
        batch_docs = documents[i:i + batch_size]
        batch_texts = [doc.page_content for doc in batch_docs]
        batch_vectors = embedding_model.embed_documents(batch_texts)
        text_embeddings.extend(zip(batch_texts, batch_vectors))
        metadatas += [doc.metadata for doc in batch_docs]

    vectorstore = OpenSearchVectorSearch(
        opensearch_url=f"https://{aoss_host}",
        engine="faiss",
        index_name=index_name,
        http_auth=awsauth,
        embedding_function=embedding_model,
        opensearch_client=opensearch_client,
        connection_class=RequestsHttpConnection
    )

    vectorstore.add_embeddings(
        text_embeddings=text_embeddings,
        metadatas=metadatas
    )
